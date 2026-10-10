# SPDX-License-Identifier: GPL-3.0-or-later
"""User regressions: restored strokes, layer changes and removed layers."""
import json
import math
import os
import traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QApplication, QTimer, QEvent, Qt, QPointF, QMouseEvent, QKeyEvent, QDialog

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}
        self.tries = 0
        self.after(self.start, 1800)

    def createActions(self, window): pass

    def after(self, fn, delay=300):
        QTimer.singleShot(delay, lambda: self.safe(fn))

    def safe(self, fn):
        try:
            if hasattr(self, 'c') and (self.c.input_busy() or self.c._pending_input):
                self.after(fn, 100)
                return
            (ROOT/'phase.json').write_text(json.dumps({'phase': fn.__name__, 'completed': self.result}))
            fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc())
            self.finish()

    def finish(self):
        (ROOT/'docs/validation/layer-lifecycle.json').write_text(json.dumps(self.result, indent=2))
        for doc in Krita.instance().documents(): doc.setModified(False)
        if hasattr(self, 'window'): self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)

    def tool(self, index):
        from linework.tools import select_tool, current_controller
        select_tool(index)
        self.c = current_controller(self.window)
        assert self.c
        self.c.poll()
        assert self.c.overlay and not self.c._error, self.c.status.text()

    def mouse(self, kind, x, y):
        self.c._tablet_until = 0
        self.c.poll()
        overlay = self.c.overlay
        assert overlay, self.c.status.text()
        overlay.sync_transform()
        pos = overlay.image_to_widget.map(QPointF(x, y))
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        QApplication.sendEvent(self.c.native_widget, QMouseEvent(kind, pos, button, buttons, Qt.KeyboardModifier.NoModifier))
        assert self.c.overlay and not self.c._error, self.c.status.text()

    def stroke(self, y):
        self.mouse(QEvent.Type.MouseButtonPress, 120, y)
        for x in range(135, 421, 15): self.mouse(QEvent.Type.MouseMove, x, y)
        self.mouse(QEvent.Type.MouseButtonRelease, 420, y)

    def key(self, key, modifiers=Qt.KeyboardModifier.NoModifier):
        for kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            QApplication.sendEvent(self.c.native_widget, QKeyEvent(kind, key, modifiers))
        assert self.c.overlay and not self.c._error, self.c.status.text()

    def data(self):
        from linework.storage import read_layer
        actual = [s.data() for s in self.c.overlay.strokes]
        assert actual == [s.data() for s in read_layer(self.doc, self.c.layer)]
        assert len(self.c.layer.shapes()) == len(actual)
        return actual

    def start(self):
        self.k = Krita.instance()
        (ROOT/'phase.json').write_text(json.dumps({'phase':'start.scan'}))
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog':
                (ROOT/'phase.json').write_text(json.dumps({'phase':'start.recovery'}))
                QDialog.reject(widget)
        if not self.k.activeDocument():
            self.tries += 1; assert self.tries < 40
            self.after(self.start); return
        (ROOT/'phase.json').write_text(json.dumps({'phase':'start.window'}))
        self.window = self.k.activeWindow()
        self.qt_window = self.window.qwindow()
        self.window.activate(); QApplication.setActiveWindow(self.qt_window)
        self.qt_window.resize(1450, 1020)
        (ROOT/'phase.json').write_text(json.dumps({'phase':'start.view'}))
        self.view = self.window.activeView(); self.doc = self.view.document()
        self.source = self.doc.activeNode()
        (ROOT/'phase.json').write_text(json.dumps({'phase':'start.preset'}))
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.view.setBrushSize(18)
        self.k.action('erase_action').setChecked(False)
        (ROOT/'phase.json').write_text(json.dumps({'phase':'start.tool'}))
        self.tool(0); self.c.smoothing.mode.setCurrentIndex(0)
        (ROOT/'phase.json').write_text(json.dumps({'phase':'start.draw'}))
        self.stroke(180); self.after(self.delete_and_restore)

    def delete_and_restore(self):
        self.original = self.c.layer
        self.initial = self.data(); assert len(self.initial) == 1
        self.uid = self.initial[0]['id']
        self.tool(3); self.c.overlay.select_strokes([self.uid])
        self.key(Qt.Key.Key_Delete); assert not self.data()
        self.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert self.data() == self.initial
        self.c.overlay.select_strokes([self.uid])
        self.mouse(QEvent.Type.MouseButtonPress, 120, 180)
        self.mouse(QEvent.Type.MouseMove, 130, 185)
        self.mouse(QEvent.Type.MouseButtonRelease, 130, 185)
        assert self.data() != self.initial
        self.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert self.data() == self.initial
        self.result['deleted_stroke_can_be_edited_after_canvas_undo'] = 'pass'
        self.tool(5); self.c.eraser_mode.setCurrentIndex(0)
        self.mouse(QEvent.Type.MouseButtonPress, 260, 180)
        self.mouse(QEvent.Type.MouseButtonRelease, 260, 180)
        assert not self.data()
        self.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert self.data() == self.initial
        self.mouse(QEvent.Type.MouseButtonPress, 260, 180)
        self.mouse(QEvent.Type.MouseButtonRelease, 260, 180)
        assert not self.data()
        self.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.result['erased_stroke_can_be_erased_again_after_canvas_undo'] = 'pass'
        self.tool(3); self.c.overlay.select_strokes([self.uid])
        self.key(Qt.Key.Key_Delete); assert not self.data()
        self.after(self.native_restore)

    def native_restore(self):
        self.k.action('edit_undo').trigger(); self.doc.waitForDone(); self.c.poll()
        assert self.data() == self.initial
        self.c.overlay.select_strokes([self.uid])
        self.mouse(QEvent.Type.MouseButtonPress, 120, 180)
        self.mouse(QEvent.Type.MouseMove, 140, 190)
        self.mouse(QEvent.Type.MouseButtonRelease, 140, 190)
        assert self.data() != self.initial
        self.after(self.native_history_checked)

    def native_history_checked(self):
        self.k.action('edit_undo').trigger(); self.doc.waitForDone(); self.c.poll()
        assert self.data() == self.initial
        self.k.action('edit_redo').trigger(); self.doc.waitForDone(); self.c.poll()
        assert self.data() != self.initial
        self.k.action('edit_undo').trigger(); self.doc.waitForDone(); self.c.poll()
        self.c.overlay.select_strokes([self.uid])
        self.key(Qt.Key.Key_Delete); assert not self.data()
        self.k.action('edit_undo').trigger(); self.doc.waitForDone(); self.c.poll()
        assert self.data() == self.initial
        self.result['native_undo_restores_geometry_and_editable_appearance_together'] = 'pass'
        self.tool(0)
        self.k.action('add_new_paint_layer').trigger()
        self.doc.waitForDone(); self.after(self.draw_on_other_layer)

    def draw_on_other_layer(self):
        active = self.doc.activeNode()
        assert active and active.type() == 'paintlayer'
        self.c.poll(); self.stroke(320)
        self.after(self.other_layer_checked)

    def other_layer_checked(self):
        from linework.storage import read_layer
        self.second = self.c.layer
        assert self.second.uniqueId() != self.original.uniqueId()
        assert len(self.data()) == 1
        assert [s.data() for s in read_layer(self.doc, self.original)] == self.initial
        self.result['drawing_after_layer_switch_preserves_previous_layer'] = 'pass'
        self.result['switch_debug'] = {'pending_before': self.c._selection_pending,
            'active_before': self.doc.activeNode().uniqueId().toString(),
            'original': self.original.uniqueId().toString()}
        self.doc.setActiveNode(self.original)
        self.result['switch_debug']['active_after_request'] = self.doc.activeNode().uniqueId().toString()
        self.after(self.draw_on_original)

    def draw_on_original(self):
        self.result['switch_debug'].update(pending_at_draw=self.c._selection_pending,
            active_at_draw=self.doc.activeNode().uniqueId().toString(),
            controller_at_draw=self.c.layer.uniqueId().toString() if self.c.layer else None)
        self.c.poll(); self.stroke(480)
        assert self.c.layer.uniqueId() == self.original.uniqueId()
        assert len(self.data()) == 2
        self.result['switching_back_edits_the_selected_linework_layer'] = 'pass'
        self.removed_id = self.original.uniqueId()
        self.k.action('remove_layer').trigger()
        self.doc.waitForDone(); self.after(self.draw_after_removal)

    def draw_after_removal(self):
        assert self.doc.nodeByUniqueID(self.removed_id) is None
        self.c.poll(); self.stroke(620)
        assert self.c.layer and self.c.layer.uniqueId() != self.removed_id
        self.after(self.removal_checked)

    def removal_checked(self):
        point = self.data()[-1]['points'][0][:2]
        assert math.dist(point, [120, 620]) < .01, point
        self.result['removing_active_linework_layer_does_not_disable_drawing'] = 'pass'
        self.result.update(result='pass', krita=self.k.version())
        self.after(self.finish)


Krita.instance().addExtension(Probe(Krita.instance()))
