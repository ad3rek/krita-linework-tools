# SPDX-License-Identifier: GPL-3.0-or-later
"""Use Krita's toolbar and size actions without leaving a Linework layer."""
import copy
import json
import math
import os
import sys
import traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import (QApplication, QDialog, QDoubleSpinBox, QEvent,
                         QMouseEvent, QPointF, QLineEdit, QKeyEvent, QTimer, Qt)

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}; self.failures = []; self.tries = 0
        sys.excepthook = self.event_error
        self.after(self.start, 1800)

    def event_error(self, kind, value, tb):
        self.failures.append(''.join(traceback.format_exception(kind, value, tb)))

    def createActions(self, window): pass

    def after(self, fn, delay=300):
        QTimer.singleShot(delay, lambda: self.safe(fn))

    def safe(self, fn):
        try:
            if hasattr(self, 'c') and (self.c.input_busy() or self.c._pending_input or self.c._brush_change is not None):
                self.after(fn, 100); return
            (ROOT/'phase.json').write_text(json.dumps({'phase': fn.__name__, 'completed': self.result}))
            fn()
        except Exception:
            self.failures.append(traceback.format_exc()); self.finish()

    def finish(self):
        self.result.update(result='fail' if self.failures else 'pass', krita=self.k.version())
        if self.failures: self.result['failures'] = self.failures
        (ROOT/'docs/validation/brush-size.json').write_text(json.dumps(self.result, indent=2))
        for doc in self.k.documents(): doc.setModified(False)
        self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)

    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows():
            window.activate(); QApplication.setActiveWindow(window.qwindow())
        if not self.k.activeDocument():
            self.tries += 1; assert self.tries < 40
            self.after(self.start); return
        self.window = self.k.activeWindow(); self.window.qwindow().resize(1450, 1020)
        self.view = self.window.activeView(); self.doc = self.view.document()
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.k.action('erase_action').setChecked(False)
        from linework.tools import select_tool, current_controller
        from linework.model import Point, Stroke
        from linework.native_brush import NativeBrushRenderer, capture_brush
        from linework.storage import write_layer
        select_tool(3); self.c = current_controller(self.window)
        assert self.c
        self.layer = self.c.create_native_layer(self.doc)
        renderer = NativeBrushRenderer(self.view)
        self.strokes = [Stroke([Point(120,180,.7),Point(450,240,.8)], width=18,
                              brush=copy.deepcopy(capture_brush(self.view)))]
        write_layer(self.doc, self.layer, self.strokes, renderer); renderer.close()
        self.c.poll(); self.initial = [s.data() for s in self.strokes]
        self.mode = 0; self.after(self.check_mode)

    def check_mode(self):
        from linework.tools import select_tool, current_controller
        from linework.storage import read_layer
        select_tool(self.mode); self.c = current_controller(self.window); self.c.poll()
        assert self.doc.activeNode().uniqueId() == self.layer.uniqueId()
        sliders = [s for s in self.window.qwindow().findChildren(QDoubleSpinBox)
                   if s.isVisible() and s.metaObject().className() == 'KisDoubleSliderSpinBox'
                   and s.suffix().strip() == 'px']
        assert len(sliders) == 1, [(s.objectName(), s.suffix()) for s in sliders]
        self.slider = sliders[0]; self.target = 32+self.mode*3
        self.editor = self.slider.findChild(QLineEdit)
        assert self.editor
        # Enter is Krita's native shortcut for editing a slider's numeric value.
        self.slider.setFocus()
        QApplication.sendEvent(self.slider, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                    Qt.KeyboardModifier.NoModifier))
        self.after(self.type_size, 50)

    def type_size(self):
        from linework.tools import select_tool, current_controller
        from linework.storage import read_layer
        editor = self.editor; target = self.target
        assert not editor.isReadOnly()
        editor.setFocus()
        def key(code, text='', modifiers=Qt.KeyboardModifier.NoModifier):
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(editor, QKeyEvent(kind, code, modifiers, text))
        key(Qt.Key.Key_A, 'a', Qt.KeyboardModifier.ControlModifier)
        for character in str(target): key(ord(character), character)
        key(Qt.Key.Key_Return)
        size = self.view.brushSize()
        if not math.isclose(size, target, abs_tol=.01):
            self.failures.append(f'mode {self.mode}: toolbar {target} px gave {size} px')
        else: self.result[f'toolbar_size_mode_{self.mode}'] = 'pass'
        self.c.native_widget.setFocus()
        self.after(self.size_actions, 100)

    def size_actions(self):
        self.previous_size = self.view.brushSize()
        self.result['size_action_enabled_'+str(self.mode)] = self.k.action('increase_brush_size').isEnabled()
        self.k.action('increase_brush_size').trigger()
        self.after(self.size_grown, 300)

    def size_grown(self):
        self.grown_size = self.view.brushSize()
        self.k.action('decrease_brush_size').trigger()
        self.after(self.size_shrunk, 300)

    def size_shrunk(self):
        from linework.tools import select_tool, current_controller
        from linework.storage import read_layer
        if not self.grown_size > self.previous_size or not self.view.brushSize() < self.grown_size:
            self.failures.append(f'mode {self.mode}: native size actions {self.previous_size}, {self.grown_size}, {self.view.brushSize()} px')
        else: self.result[f'native_size_actions_mode_{self.mode}'] = 'pass'
        assert [s.data() for s in read_layer(self.doc,self.layer)] == self.initial
        self.mode += 1
        if self.mode < 6: self.after(self.check_mode)
        else:
            self.result['size_changes_preserve_existing_strokes_and_active_layer'] = 'pass'
            select_tool(0); self.c = current_controller(self.window); self.c.poll()
            self.view.setBrushSize(31)
            self.after(self.draw)

    def pointer(self, kind, x, y):
        self.c._tablet_until = 0
        o = self.c.overlay; o.sync_transform(); pos = o.image_to_widget.map(QPointF(x,y))
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        QApplication.sendEvent(self.c.native_widget, QMouseEvent(kind,pos,button,buttons,Qt.KeyboardModifier.NoModifier))

    def draw(self):
        self.pointer(QEvent.Type.MouseButtonPress, 120,400)
        self.pointer(QEvent.Type.MouseMove, 420,400)
        self.pointer(QEvent.Type.MouseButtonRelease, 420,400)
        self.after(self.drawn)

    def drawn(self):
        from linework.storage import read_layer
        strokes = read_layer(self.doc,self.layer)
        assert len(strokes) == 2 and math.isclose(strokes[-1].width,31)
        assert strokes[0].data() == self.initial[0]
        self.result['next_stroke_captures_new_size_without_layer_switch'] = 'pass'
        self.window.qwindow().grab().save(str(ROOT/'docs/images/brush-size.png'))
        self.finish()


Krita.instance().addExtension(Probe(Krita.instance()))
