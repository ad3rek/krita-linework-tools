# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify release, subsequent strokes and input delivered during native waits."""
import json
import os
import sys
import time
import traceback
from pathlib import Path
from krita import Krita, Extension, ManagedColor
from linework.qt import QEvent, QPointF, QTimer, Qt
from linework.qt import QColor, QKeyEvent, QMouseEvent, tablet_event
from linework.qt import QApplication, QDialog

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}; self.tries = 0
        self.event_error=None
        sys.excepthook=self.on_event_error
        self.after(self.start, 1800)

    def on_event_error(self, kind, value, tb):
        self.event_error=''.join(traceback.format_exception(kind,value,tb))
        (ROOT/'event-error.txt').write_text(self.event_error)

    def createActions(self, window): pass

    def after(self, fn, delay=100):
        QTimer.singleShot(delay, lambda: self.safe(fn))

    def safe(self, fn):
        try:
            if hasattr(self, 'c') and (self.c.input_busy() or self.c._pending_input):
                self.after(fn,100)
                return
            if self.event_error: raise AssertionError(self.event_error)
            (ROOT/'phase.json').write_text(json.dumps({'phase': fn.__name__, 'mode': getattr(self, 'mode', None), 'completed': self.result}))
            fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc())
            self.finish()

    def after_input(self, fn, delay=100):
        # Native waits pump timers while the captured gesture is still being
        # replayed. A fixed delay can inspect/close the canvas inside that wait.
        deadline = time.monotonic()+90
        def ready():
            busy = self.c.input_busy() or bool(self.c._pending_input)
            if busy:
                self.result['queued_input_check_deferrals'] = self.result.get('queued_input_check_deferrals', 0)+1
                assert time.monotonic() < deadline, 'Queued input did not drain'
                self.after(ready, 100)
            else:
                fn()
        self.after(ready, delay)

    def finish(self):
        (ROOT/'docs/validation/stroke-lifecycle.json').write_text(json.dumps(self.result, indent=2))
        for doc in Krita.instance().documents(): doc.setModified(False)
        if hasattr(self, 'window'): self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)

    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows():
            QApplication.setActiveWindow(window.qwindow()); window.activate()
        if not self.k.activeDocument():
            self.tries += 1; assert self.tries < 40
            self.after(self.start); return
        self.window = self.k.activeWindow(); self.window.qwindow().resize(1450, 1020)
        self.view = self.window.activeView(); self.doc = self.view.document()
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.view.setBrushSize(16); self.view.setPaintingOpacity(1)
        self.view.setForeGroundColor(ManagedColor.fromQColor(QColor('#172f61'), self.view.canvas()))
        self.k.action('erase_action').setChecked(False)
        from linework.tools import select_tool, current_controller
        select_tool(0); self.c = current_controller(self.window); self.c.poll()
        assert self.c.overlay, self.c.status.text()
        self.mode = 0; self.run_mode()

    def pointer(self, kind, x, y, tablet=False, pressure=.8):
        o = self.c.overlay
        assert o, self.c.status.text()
        o.sync_transform(); pos = o.image_to_widget.map(QPointF(x, y))
        buttons = Qt.MouseButton.NoButton if kind == 'release' else Qt.MouseButton.LeftButton
        if tablet:
            etype = {'press': QEvent.Type.TabletPress, 'move': QEvent.Type.TabletMove,
                     'release': QEvent.Type.TabletRelease}[kind]
            ev = tablet_event(etype, pos, 0 if kind == 'release' else pressure,
                              Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
        else:
            self.c._tablet_until = 0
            etype = {'press': QEvent.Type.MouseButtonPress, 'move': QEvent.Type.MouseMove,
                     'release': QEvent.Type.MouseButtonRelease, 'double': QEvent.Type.MouseButtonDblClick}[kind]
            ev = QMouseEvent(etype, pos, Qt.MouseButton.NoButton if kind == 'move' else Qt.MouseButton.LeftButton,
                             buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.c.native_widget, ev)

    def stroke(self, y, tablet=False, double=False):
        self.pointer('double' if double else 'press', 120, y, tablet)
        for x in range(130, 431, 10): self.pointer('move', x, y, tablet)
        self.pointer('release', 430, y, tablet)

    def assert_saved(self, count, ys):
        from linework.storage import read_layer
        assert self.c.overlay and not self.c._error, self.c.status.text()
        self.doc.waitForDone(); self.c.poll()
        assert len(self.c.overlay.strokes) == count, (count, len(self.c.overlay.strokes))
        assert [s.data() for s in read_layer(self.doc, self.c.layer)] == [s.data() for s in self.c.overlay.strokes]
        assert self.c.overlay.draft is None and self.c.overlay.smoother is None
        for y in ys:
            pixels = bytes(self.c.layer.projectionPixelData(200, y-8, 80, 16))
            assert sum(pixels[3::4]) > 1000, (y, sum(pixels[3::4]))

    def run_mode(self):
        self.c.smoothing.mode.setCurrentIndex(self.mode)
        self.c.smoothing.fields[6].setChecked(False)
        self.c.smoothing.fields[7].setChecked(True)
        # Rapid input without inter-move timers must still survive release.
        self.stroke(100+120*self.mode)
        self.stroke(150+120*self.mode, tablet=True)
        self.after(self.checked_mode, 250)

    def checked_mode(self):
        self.assert_saved(2*(self.mode+1), [100+120*self.mode, 150+120*self.mode])
        self.result['rapid_mouse_and_tablet_mode_'+str(self.mode)] = 'pass'
        self.mode += 1
        if self.mode < 4: self.run_mode()
        else:
            self.c.smoothing.mode.setCurrentIndex(0)
            self.stroke(600, double=True)
            self.after(self.nested_input, 250)

    def nested_input(self):
        self.assert_saved(9, [600])
        self.result['double_click_starts_next_brush_stroke'] = 'pass'
        # A native image wait pumps Qt. Deliver the next pen gesture at that
        # boundary deterministically, before the current render has returned.
        renderer = self.c.overlay.renderer; original = renderer._paint
        def paint(*args):
            renderer._paint = original
            self.stroke(710, tablet=True)
            return original(*args)
        renderer._paint = paint
        self.stroke(650, tablet=True)
        self.after_input(self.nested_checked, 400)

    def nested_checked(self):
        self.assert_saved(11, [650, 710])
        self.result['input_during_native_wait_is_ordered_and_both_strokes_persist'] = 'pass'
        renderer = self.c.overlay.renderer; original = renderer._paint
        def paint(*args):
            renderer._paint = original
            self.stroke(850)
            for key in (Qt.Key.Key_Z, Qt.Key.Key_Y):
                for kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
                    QApplication.sendEvent(self.c.native_widget, QKeyEvent(kind, key, Qt.KeyboardModifier.ControlModifier))
            return original(*args)
        renderer._paint = paint
        self.stroke(800)
        self.after_input(self.mouse_checked, 400)

    def mouse_checked(self):
        self.assert_saved(13, [800, 850])
        self.result['queued_mouse_and_shortcuts_preserve_event_order'] = 'pass'
        self.stroke(770, tablet=True)
        self.after(self.missing_release, 250)

    def missing_release(self):
        self.assert_saved(14, [770])
        self.pointer('press', 500, 110, tablet=True)
        self.pointer('move', 760, 110, tablet=True)
        self.pointer('press', 500, 170, tablet=True)
        self.pointer('move', 760, 170, tablet=True)
        self.pointer('release', 760, 170, tablet=True)
        self.after(self.done, 250)

    def done(self):
        self.assert_saved(16, [770])
        for y in (110, 170):
            assert sum(bytes(self.c.layer.projectionPixelData(600, y-8, 80, 16))[3::4]) > 1000
        self.result['new_press_preserves_previous_path_after_missing_release'] = 'pass'
        expected = [s.data() for s in self.c.overlay.strokes]
        self.c.overlay.undo(); assert len(self.c.overlay.strokes) == 15
        self.c.overlay.redo(); assert [s.data() for s in self.c.overlay.strokes] == expected
        self.result['individual_strokes_keep_separate_undo_steps'] = 'pass'
        path = ROOT/'examples/stroke-lifecycle.kra'
        assert self.doc.saveAs(str(path))
        from linework.storage import read_layer
        self.loaded = self.k.openDocument(str(path)); assert self.loaded
        self.loaded_layer = self.loaded.nodeByUniqueID(self.c.layer.uniqueId())
        assert [s.data() for s in read_layer(self.loaded, self.loaded_layer)] == expected
        self.window.addView(self.loaded)
        self.loaded.refreshProjection()
        self.after(self.reopened, 500)

    def reopened(self):
        self.loaded.waitForDone()
        pixels = bytes(self.loaded_layer.projectionPixelData(200, 650-8, 80, 16))
        assert sum(pixels[3::4]) > 1000, sum(pixels[3::4])
        self.result['subsequent_drawing_and_kra_round_trip'] = 'pass'
        self.result.update(result='pass', krita=self.k.version())
        self.window.qwindow().grab().save(str(ROOT/'docs/images/stroke-lifecycle.png'))
        self.finish()


Krita.instance().addExtension(Probe(Krita.instance()))
