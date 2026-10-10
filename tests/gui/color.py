# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify foreground changes, native pixels, grouping and persisted colors."""
import copy
import json
import os
import traceback
from pathlib import Path
from krita import Krita, Extension, ManagedColor
from linework.qt import QTimer, Qt
from linework.qt import QColor
from linework.qt import QApplication, QDialog, QDockWidget

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}; self.tries = 0
        self.after(self.start, 1800)

    def createActions(self, window): pass

    def after(self, fn, delay=100):
        QTimer.singleShot(delay, lambda: self.safe(fn))

    def safe(self, fn):
        try: fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc())
            self.finish()

    def finish(self):
        (ROOT/'docs/validation/color.json').write_text(json.dumps(self.result, indent=2))
        for doc in Krita.instance().documents(): doc.setModified(False)
        if hasattr(self, 'window'): self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)

    def wait_update(self, fn):
        if self.c._brush_change or self.c._pending_color or self.c.color_timer.isActive():
            self.after(lambda: self.wait_update(fn)); return
        assert self.c.overlay and not self.c._error, self.c.status.text()
        fn()

    def data(self): return [s.data() for s in self.c.overlay.strokes]

    def set_color(self, color):
        self.view.setForeGroundColor(ManagedColor.fromQColor(QColor(color), self.view.canvas()))
        self.c.poll()

    def pixel(self, y):
        return tuple(bytes(self.layer.projectionPixelData(300, y, 1, 1)))

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
        self.source = self.doc.activeNode()
        self.source_before = bytes(self.source.pixelData(0, 0, self.doc.width(), self.doc.height()))
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.k.action('erase_action').setChecked(False)
        from linework.tools import select_tool, current_controller
        from linework.model import Stroke, Point
        from linework.native_brush import capture_brush, NativeBrushRenderer
        from linework.storage import write_layer
        select_tool(3); self.c = current_controller(self.window)
        self.layer = self.c.create_native_layer(self.doc, 'vectorlayer')
        brush = capture_brush(self.view)
        strokes = []
        for y, color, preset in [(180, '#203040', brush), (350, '#274b72', None), (520, '#804020', brush)]:
            points = [Point(150, y, .7, handle_out=(50, 0)),
                      Point(300, y, .8, handle_in=(-50, 0), handle_out=(50, 0)),
                      Point(450, y, .9, handle_in=(-50, 0))]
            strokes.append(Stroke(points, width=24, color=color, brush=copy.deepcopy(preset)))
        renderer = NativeBrushRenderer(self.view)
        write_layer(self.doc, self.layer, strokes, renderer); renderer.close()
        self.uids = [s.uid for s in strokes]
        self.after(self.select, 300)

    def select(self):
        self.c.poll(); self.c.overlay.select_strokes(self.uids[:2])
        self.before = self.data(); self.depth = len(self.c.overlay.history.undo_stack)
        self.untouched = {s.name(): s.toSvg() for s in self.layer.shapes()}['lw_'+self.uids[2]]
        # Automatic recoloring must respect selection even with All strokes set.
        self.c.brush_scope.setCurrentIndex(1)
        self.set_color('#ff0000'); self.set_color('#00ff00'); self.set_color('#df1a25')
        self.after(lambda: self.wait_update(self.recolored), 550)

    def recolored(self):
        expected = copy.deepcopy(self.before)
        expected[0]['color'] = expected[1]['color'] = '#df1a25'
        assert self.data() == expected
        assert len(self.c.overlay.history.undo_stack) == self.depth+1
        assert self.c.overlay.selection.ids() == set(self.uids[:2])
        assert {s.name(): s.toSvg() for s in self.layer.shapes()}['lw_'+self.uids[2]] == self.untouched
        for y in (180, 350):
            blue, green, red, alpha = self.pixel(y)
            assert alpha > 0 and red > green+20 and red > blue+20, self.pixel(y)
        self.result['foreground_recolors_native_and_smooth_selected_strokes_only'] = 'pass'
        self.result['slider_changes_debounced_into_one_undo_preserve_geometry_pressure_and_brush'] = 'pass'
        self.c.overlay.undo(); assert self.data() == self.before
        self.c.overlay.redo(); assert self.data() == expected
        self.result['grouped_color_undo_redo'] = 'pass'
        self.set_color('#df1a25')
        depth = len(self.c.overlay.history.undo_stack)
        self.c.apply_color_button.click()  # All strokes: also changes the untouched third curve.
        self.depth = depth
        self.after(lambda: self.wait_update(self.all_done))

    def all_done(self):
        assert [s.color for s in self.c.overlay.strokes] == ['#df1a25']*3
        assert len(self.c.overlay.history.undo_stack) == self.depth+1
        self.result['explicit_button_applies_to_entire_layer'] = 'pass'
        self.c.overlay.undo()
        self.c.brush_scope.setCurrentIndex(0)
        self.c.overlay.select_strokes([self.uids[2]])
        self.before = self.data()
        from linework.tools import select_tool
        select_tool(4)
        self.set_color('#164fdc')
        self.after(lambda: self.wait_update(self.thickness_done), 550)

    def thickness_done(self):
        expected = copy.deepcopy(self.before); expected[2]['color'] = '#164fdc'
        assert self.data() == expected
        blue, green, red, alpha = self.pixel(520)
        assert alpha > 0 and blue > red+20 and blue > green+20, self.pixel(520)
        self.result['thickness_tool_recolors_selected_native_stroke'] = 'pass'
        self.layer.setLocked(True)
        self.c.apply_color('#ff00ff'); assert self.data() == expected
        self.layer.setLocked(False)
        self.result['locked_layer_preserved'] = 'pass'
        self.kra = ROOT/'examples/color.kra'; assert self.doc.saveAs(str(self.kra))
        from linework.storage import read_layer
        loaded = self.k.openDocument(str(self.kra))
        node = loaded.nodeByUniqueID(self.layer.uniqueId())
        assert [s.data() for s in read_layer(loaded, node)] == expected
        loaded.setModified(False); loaded.close()
        assert bytes(self.source.pixelData(0, 0, self.doc.width(), self.doc.height())) == self.source_before
        self.result['kra_roundtrip_and_original_raster_preserved'] = 'pass'
        # Drawing colors belong to future strokes; old selections keep theirs.
        from linework.tools import select_tool
        select_tool(0); self.set_color('#20b84f')
        self.before = self.data()
        self.after(self.drawing_mode, 550)

    def drawing_mode(self):
        assert self.data() == self.before
        self.result['drawing_foreground_does_not_recolor_existing_selection'] = 'pass'
        from linework.tools import select_tool
        select_tool(4)
        self.c.overlay.select_strokes([self.uids[2]])
        assert self.data() == self.before
        self.result['activating_editor_and_selecting_stroke_preserve_saved_color'] = 'pass'
        # The explicit selected-scope action also works without a color change.
        self.c.apply_color_button.click()
        self.after(lambda: self.wait_update(self.selected_done))

    def selected_done(self):
        expected = copy.deepcopy(self.before); expected[2]['color'] = '#20b84f'
        assert self.data() == expected
        self.c.overlay.undo(); assert self.data() == self.before
        self.c.overlay.redo(); assert self.data() == expected
        blue, green, red, alpha = self.pixel(520)
        assert alpha > 0 and green > red+20 and green > blue+20, self.pixel(520)
        assert self.doc.saveAs(str(self.kra))
        self.result['explicit_button_selected_scope_with_unchanged_foreground'] = 'pass'
        self.after(self.capture, 300)

    def capture(self):
        self.c.status.hide()
        options = self.window.qwindow().findChild(QDockWidget, 'sharedtooldocker')
        options.show(); options.raise_()
        self.window.qwindow().resizeDocks([options], [650], Qt.Orientation.Vertical)
        QApplication.processEvents()
        self.window.qwindow().grab().save(str(ROOT/'docs/images/color-editing.png'))
        self.result['result'] = 'pass'; self.finish()


Krita.instance().addExtension(Probe(Krita.instance()))
