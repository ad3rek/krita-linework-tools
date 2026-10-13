# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare actual commits, legacy reload and compact saves in isolated Krita."""
import copy, json, os, statistics, time, traceback, zipfile
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QApplication, QTimer, QImage, QPainter, QColor, Qt, QEventLoop, QDialog

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


def timed(fn, count=3):
    values = []
    for _ in range(count):
        start = time.perf_counter(); fn(); values.append((time.perf_counter()-start)*1000)
    return round(statistics.median(values), 3)


class Probe(Extension):
    def setup(self):
        self.result = {}; self.after(self.start, 1800)
    def createActions(self, window): pass
    def after(self, fn, delay=100): QTimer.singleShot(delay, lambda: self.safe(fn))
    def safe(self, fn):
        try:
            from linework.native_brush import native_busy
            if native_busy():
                self.after(fn, 100); return
            (ROOT/'phase.json').write_text(json.dumps({'phase': fn.__name__, 'completed': self.result}))
            fn()
        except Exception as error:
            from linework.animation import AnimationBusy
            if isinstance(error, AnimationBusy):
                self.after(fn, 100); return
            self.result.update(result='fail', traceback=traceback.format_exc()); self.finish()
    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows():
            window.activate(); QApplication.setActiveWindow(window.qwindow())
        self.window = self.k.activeWindow() or next(iter(self.k.windows()), None)
        if self.window is None:
            self.result['startup_state'] = {'documents':len(self.k.documents()), 'windows':len(self.k.windows()),
                                           'widgets':[w.metaObject().className() for w in QApplication.topLevelWidgets()]}
            self.after(self.start, 200); return
        self.result.pop('startup_state', None)
        QApplication.instance().setQuitOnLastWindowClosed(False)
        (ROOT/'phase.json').write_text(json.dumps({'phase':'create_document'}))
        self.doc = self.k.createDocument(2048, 2048, 'Linework compact test', 'RGBA', 'U8', 'sRGB-elle-V2-srgbtrc.icc', 72)
        self.doc.setBatchmode(True)
        (ROOT/'phase.json').write_text(json.dumps({'phase':'add_view'}))
        self.window.addView(self.doc)
        self.doc.setBatchmode(False)
        self.after(self.prepare, 300)
    def prepare(self):
        from linework import animation
        from linework.model import Point, Stroke
        from linework.native_brush import NativeBrushRenderer, capture_brush
        from linework.storage import write_layer, metadata
        self.view = self.window.activeView()
        self.view.setCurrentBrushPreset(self.k.resources('preset')['u) Pixel Art'])
        self.k.action('erase_action').setChecked(False)
        brush = capture_brush(self.view)
        self.strokes = []
        for i in range(300):
            x, y = 30+(i%18)*106, 30+(i//18)*100
            self.strokes.append(Stroke([Point(x,y,1),Point(x+35,y+15,.7),Point(x+75,y+5,1)], width=8, brush=copy.deepcopy(brush)))
        self.renderer = NativeBrushRenderer(self.view)
        capability = animation.compact_bridge
        try:
            animation.compact_bridge = lambda: False
            self.layer = write_layer(self.doc, None, self.strokes, self.renderer)
        finally:
            animation.compact_bridge = capability
        assert metadata(self.doc)['version'] == 7
        self.expected = [stroke.data() for stroke in self.strokes]
        self.old_pixels = bytes(self.layer.pixelData(0,0,2048,2048))
        self.legacy_bytes = len(bytes(self.doc.annotation('org.felipe.linework.v1')))
        self.legacy_path = ROOT/'examples/legacy-v7.kra'
        assert self.doc.saveAs(str(self.legacy_path))
        self.result['legacy_v7_file_created'] = 'pass'
        self.renderer.close(); self.renderer = None
        self.source_doc = self.doc
        self.doc = self.k.openDocument(str(self.legacy_path)); assert self.doc
        self.window.addView(self.doc)
        self.after(self.reloaded, 300)
    def reloaded(self):
        from linework import animation
        from linework.storage import metadata, layer_id, read_layer, write_layer
        from linework.native_brush import NativeBrushRenderer
        self.doc.waitForDone(); self.view = self.window.activeView()
        saved = metadata(self.doc)['layers']
        self.layer = next(layer for layer in self.doc.rootNode().findChildNodes('',True,False,'paintlayer')
                          if saved.get(layer_id(layer), {}).get('kind') == 'animated')
        self.strokes = read_layer(self.doc, self.layer)
        assert [stroke.data() for stroke in self.strokes] == self.expected
        assert bytes(self.layer.pixelData(0,0,2048,2048)) == self.old_pixels
        self.result['legacy_reload_retains_exact_geometry_and_pixels'] = 'pass'
        self.doc.setActiveNode(self.layer)
        self.renderer = NativeBrushRenderer(self.view)
        write_layer(self.doc, self.layer, self.strokes, self.renderer)
        assert metadata(self.doc)['version'] == 8
        assert [stroke.data() for stroke in read_layer(self.doc, self.layer)] == self.expected
        assert bytes(self.layer.pixelData(0,0,2048,2048)) == self.old_pixels
        self.result['legacy_frame_migrates_on_edit_with_exact_pixels'] = 'pass'
        self.result['strokes'] = len(self.strokes)
        self.result['legacy_annotation_bytes'] = self.legacy_bytes
        self.result['compact_annotation_bytes'] = len(bytes(self.doc.annotation('org.felipe.linework.v1')))
        self.result['metadata_reduction_pct'] = round(100*(1-self.result['compact_annotation_bytes']/self.legacy_bytes),3)
        payload = animation.record(self.doc,self.layer)
        def original_compose(document, payload, hidden=()):
            from linework.model import load_strokes
            from linework.editor import painter_path
            image = QImage(document.width(),document.height(),QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent); painter = QPainter(image)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing); painter.setPen(Qt.PenStyle.NoPen)
                for stroke in load_strokes(payload['strokes']):
                    if stroke.uid in hidden: continue
                    if stroke.brush:
                        bounds,pixels = animation.appearance(payload,stroke)
                        painter.setOpacity(1); painter.drawImage(bounds,pixels)
                    else:
                        painter.setOpacity(stroke.opacity); painter.setBrush(QColor(stroke.color))
                        painter.drawPath(painter_path(stroke))
            finally: painter.end()
            return image
        assert original_compose(self.doc,payload) == animation.compose(self.doc,payload)
        self.result['cached_and_original_composition_pixels_equal'] = 'pass'
        self.result['original_compose_ms'] = timed(lambda: original_compose(self.doc,payload))
        self.result['cached_compose_ms'] = timed(lambda: animation.compose(self.doc,payload))
        pack, compose = animation.compact_record, animation.compose
        def edit():
            self.strokes[-1].points[1].y += 1
            write_layer(self.doc,self.layer,self.strokes,self.renderer)
        try:
            animation.compact_record = lambda value: value
            animation.compose = original_compose
            edit()  # Establish a legacy payload before timing.
            self.result['legacy_full_commit_ms'] = timed(edit)
        finally:
            animation.compact_record, animation.compose = pack, compose
        edit()  # Establish the compact payload and warm appearances.
        self.result['optimized_full_commit_ms'] = timed(edit)
        self.after(self.undo_check, 200)
    def undo_check(self):
        from linework.storage import read_layer
        self.expected = [stroke.data() for stroke in self.strokes]
        self.new_pixels = bytes(self.layer.pixelData(0,0,2048,2048))
        self.k.action('edit_undo').trigger(); self.doc.waitForDone()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        assert [stroke.data() for stroke in read_layer(self.doc,self.layer)] != self.expected
        self.k.action('edit_redo').trigger(); self.doc.waitForDone()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        assert [stroke.data() for stroke in read_layer(self.doc,self.layer)] == self.expected
        assert bytes(self.layer.pixelData(0,0,2048,2048)) == self.new_pixels
        self.result['compact_native_undo_redo_restores_exact_geometry_and_pixels'] = 'pass'
        self.path = ROOT/'examples/compact-v8.kra'
        assert self.doc.saveAs(str(self.path))
        with zipfile.ZipFile(self.path) as archive:
            data = json.loads(archive.read(next(name for name in archive.namelist() if name.endswith('/annotations/org.felipe.linework.v1'))))
        assert data['version'] == 8
        frames = next(item['frames'] for item in data['layers'].values() if item.get('kind')=='animated')
        assert len(frames['0']['brushes']) == 1
        assert all('brush_ref' in item and 'brush' not in item for item in frames['0']['strokes'])
        self.result['native_save_retains_version_8_and_one_shared_preset'] = 'pass'
        self.renderer.close(); self.renderer=None
        self.source_doc2 = self.doc
        self.doc = self.k.openDocument(str(self.path)); assert self.doc
        self.window.addView(self.doc)
        self.after(self.final_reload,300)
    def final_reload(self):
        from linework.storage import metadata,layer_id,read_layer
        self.doc.waitForDone()
        saved=metadata(self.doc)['layers']
        self.layer=next(layer for layer in self.doc.rootNode().findChildNodes('',True,False,'paintlayer')
                        if saved.get(layer_id(layer),{}).get('kind')=='animated')
        assert [stroke.data() for stroke in read_layer(self.doc,self.layer)]==self.expected
        assert bytes(self.layer.pixelData(0,0,2048,2048))==self.new_pixels
        self.result['compact_kra_reopens_with_exact_geometry_and_pixels']='pass'
        self.result.update(result='pass',krita=self.k.version())
        self.finish()
    def finish(self):
        from linework.native_brush import native_busy
        if native_busy():
            self.after(self.finish, 100); return
        (ROOT/'docs/validation/performance-lightweight.json').write_text(json.dumps(self.result,indent=2))
        if getattr(self,'renderer',None): self.renderer.close()
        for document in Krita.instance().documents(): document.setModified(False)
        self.source_doc=self.source_doc2=self.doc=self.layer=self.view=self.renderer=None
        if hasattr(self,'window'): self.window.qwindow().close()
        QTimer.singleShot(300,QApplication.instance().quit)

Krita.instance().addExtension(Probe(Krita.instance()))
