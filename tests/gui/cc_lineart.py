# SPDX-License-Identifier: GPL-3.0-or-later
"""Run inside an isolated Krita with the CC BY Pepper fixture open.

LINEWORK_TEST_ROOT must point at the checkout. This probe never opens the
user's artwork and closes only its isolated test application's documents.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import math
import os
import time
import traceback
from pathlib import Path
from krita import Krita, Extension
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QDialog

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {'fixture': 'examples/pepper-lineart.png', 'version': '0.1.1'}
        self.tries = 0
        self.observer = QTimer()
        self.observer.setInterval(5)
        self.observer.timeout.connect(self.observe)
        self.reads = self.reads_during_write = 0
        self.scene_write = False
        self.reads_during_scene_write = 0
        self.after(self.start, 1800)

    def createActions(self, window):
        pass

    def safe(self, function):
        try:
            print('GUI stage:', getattr(function, '__name__', str(function)), flush=True)
            function()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc())
            self.finish()

    def after(self, function, delay=100):
        QTimer.singleShot(delay, lambda: self.safe(function))

    def observe(self):
        # Replicate another plugin enumerating native vector shapes while
        # Linework prepares and commits a bulk operation.
        if hasattr(self, 'layer'):
            self.reads += 1
            self.reads_during_write += int(self.c._writing)
            self.reads_during_scene_write += int(self.scene_write)
            for shape in self.layer.shapes():
                shape.name()

    def finish(self):
        self.observer.stop()
        self.result['observer_reads'] = self.reads
        self.result['observer_reads_during_preparation'] = self.reads_during_write
        self.result['observer_reads_during_scene_mutation'] = self.reads_during_scene_write
        path = ROOT/'docs/validation/cc-lineart.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.result, indent=2, ensure_ascii=False)+'\n')
        for document in Krita.instance().documents():
            document.setModified(False)
        if hasattr(self, 'window'):
            self.window.qwindow().close()
        QTimer.singleShot(400, QApplication.instance().quit)

    def capture(self, name, target=None):
        self.doc.waitForDone()
        (target or self.window.qwindow()).grab().save(str(ROOT/'docs/images'/name))

    def data(self):
        return [stroke.data() for stroke in self.c.overlay.strokes]

    def wait_update(self, function):
        if self.c._brush_change:
            self.after(lambda: self.wait_update(function))
            return
        assert not self.c._error, self.c.status.text()
        function()

    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog':
                QDialog.reject(widget)
        for window in self.k.windows():
            QApplication.setActiveWindow(window.qwindow())
            window.activate()
        if not self.k.activeDocument():
            self.tries += 1
            assert self.tries < 40
            self.after(self.start)
            return
        self.window = self.k.activeWindow()
        self.window.qwindow().resize(1500, 1060)
        self.view = self.window.activeView()
        self.doc = self.view.document()
        self.source = self.doc.activeNode()
        self.source.setName('Raster — David Revoy (CC BY 4.0)')
        self.before = bytes(self.source.pixelData(0, 0, self.doc.width(), self.doc.height()))
        self.result['source_size'] = [self.doc.width(), self.doc.height()]
        self.result['source_color_model'] = self.source.colorModel()
        assert self.source.colorModel() == 'GRAYA'
        self.result['source_pixels_sha256'] = hashlib.sha256(self.before).hexdigest()
        from linework.vectorize import open_vectorizer
        self.dialog = open_vectorizer(self.window)
        self.dialog.resize(1240, 950)
        self.preview_begin = time.perf_counter()
        self.after(self.preview_ready)

    def preview_ready(self):
        d = self.dialog
        if d.worker:
            self.after(self.preview_ready)
            return
        assert d.strokes, d.info.text()
        self.result['preview'] = {
            'strokes': len(d.strokes), 'anchors': sum(len(s.points) for s in d.strokes),
            'status': d.info.text(), 'mode': d.mode.currentIndex(),
            'threshold': d.threshold.value(), 'despeckle': d.noise.value(),
            'accuracy': d.accuracy.value(), 'maximum_width': d.maximum_width.value(),
            'elapsed_with_poll_seconds': time.perf_counter()-self.preview_begin}
        assert bytes(self.source.pixelData(0, 0, self.doc.width(), self.doc.height())) == self.before
        self.result['preview_preserves_source_pixels'] = 'pass'
        d.compare.setCurrentIndex(2)
        self.after(self.preview_capture, 200)

    def preview_capture(self):
        self.capture('pepper-vectorize-preview.png', self.dialog)
        d = self.dialog
        old = d.preview._scale
        d.preview.zoom_by(1.5)
        assert d.preview._scale > old and not d.preview._fit
        d.preview.fit_to_view()
        assert d.preview._fit
        self.result['preview_zoom_and_fit'] = 'pass'
        d.apply_button.click()
        self.after(self.converted, 300)

    def converted(self):
        from linework.tools import current_controller, select_tool
        self.c = current_controller(self.window)
        self.c.poll()
        assert self.c.overlay and self.c.layer
        self.layer = self.c.layer
        self.layer.setName('Linework — Pepper (CC BY 4.0)')
        assert self.layer.type() == 'vectorlayer'
        assert len(self.c.overlay.strokes) == self.result['preview']['strokes']
        assert not self.source.visible()
        self.result['new_native_linework_layer_and_preserved_raster'] = 'pass'
        self.original = copy.deepcopy(self.data())
        self.capture('pepper-vectorized.png')
        import linework.storage as storage
        original_guard = storage.shape_write
        @contextmanager
        def instrumented_guard(layer):
            with original_guard(layer):
                self.scene_write = True
                try:
                    yield
                finally:
                    self.scene_write = False
        storage.shape_write = instrumented_guard
        self.observer.start()
        self.view.setCurrentBrushPreset(self.k.resources('preset')['u) Pixel Art'])
        self.k.action('erase_action').setChecked(False)
        self.c.brush_scope.setCurrentIndex(1)
        self.c.update_controls()
        assert self.c.apply_brush_button.isEnabled()
        self.brush_begin = time.perf_counter()
        self.c.apply_brush_button.click()
        self.after(lambda: self.wait_update(self.brush_done))

    def brush_done(self):
        self.result['whole_layer_brush_seconds'] = time.perf_counter()-self.brush_begin
        after = self.data()
        assert all(s['brush']['name'] == 'u) Pixel Art' for s in after)
        assert [{k: v for k, v in s.items() if k != 'brush'} for s in after] == self.original
        self.c.overlay.undo()
        assert self.data() == self.original
        self.c.overlay.redo()
        assert self.data() == after
        self.result['all_strokes_native_preset_geometry_preserved_one_undo_redo'] = 'pass'
        self.brushed = copy.deepcopy(after)
        self.c.overlay.select_all()
        self.thickness_begin = time.perf_counter()
        self.c.thickness.setValue(4)
        self.after(lambda: self.wait_update(self.thickness_done))

    def thickness_done(self):
        from linework.native_brush import point_thickness
        after = self.data()
        self.result['whole_layer_thickness_seconds'] = time.perf_counter()-self.thickness_begin
        for old, new in zip(self.brushed, after):
            stripped = copy.deepcopy(new)
            stripped.pop('thickness_profile', None)
            assert stripped == old
        for stroke in self.c.overlay.strokes:
            assert all(math.isclose(point_thickness(stroke, i), 4, abs_tol=1e-8)
                       for i in range(len(stroke.points)))
        self.c.overlay.undo()
        assert self.data() == self.brushed
        self.c.overlay.redo()
        assert self.data() == after
        self.result['all_point_diameters_raw_pressure_and_handles_preserved_one_undo_redo'] = 'pass'
        self.modified = copy.deepcopy(after)
        # A regular point edit must rerender a fitted/imported native stroke.
        stroke = max(self.c.overlay.strokes, key=lambda s: len(s.points))
        index = len(stroke.points)//2
        stroke.points[index].x += 6
        stroke.points[index].y += 3
        self.c.overlay.commit()
        edited = self.data()
        assert edited != self.modified
        self.c.overlay.undo()
        assert self.data() == self.modified
        self.c.overlay.redo()
        assert self.data() == edited
        self.c.overlay.undo()
        self.result['point_edit_rerenders_and_undo_redo_restores_data'] = 'pass'
        assert self.reads > 0 and self.reads_during_scene_write == 0
        self.result['vector_observer_during_bulk_operations'] = 'pass'
        self.observer.stop()
        from linework.tools import select_tool
        select_tool(4)
        strokes = sorted(self.c.overlay.strokes, key=lambda s: len(s.points), reverse=True)[:3]
        self.c.overlay.selection.set_points([(s.uid, len(s.points)//2) for s in strokes])
        self.c.overlay.selectedChanged.emit()
        self.c.overlay.update()
        self.after(self.save_result, 300)

    def save_result(self):
        self.capture('pepper-native-thickness.png')
        path = ROOT/'examples/pepper-linework.kra'
        assert self.doc.saveAs(str(path))
        from linework.storage import read_layer
        loaded = self.k.openDocument(str(path))
        node = loaded.nodeByUniqueID(self.layer.uniqueId())
        assert [s.data() for s in read_layer(loaded, node)] == self.data()
        loaded.setModified(False)
        loaded.close()
        assert bytes(self.source.pixelData(0, 0, self.doc.width(), self.doc.height())) == self.before
        self.result['kra_roundtrip_and_source_pixels_unchanged'] = 'pass'
        self.result['result'] = 'pass'
        self.finish()


Krita.instance().addExtension(Probe(Krita.instance()))
