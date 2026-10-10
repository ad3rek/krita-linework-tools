# SPDX-License-Identifier: GPL-3.0-or-later
"""Vectorize synthetic pixels into the same Timeline-ready Linework layer."""
import json, os, time, traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QDialog, QApplication, QByteArray, QColor, QImage, QPainter, QPen, QTimer
ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}; self.tries = 0; self.mode = 0; self.layers = []
        self.after(self.start, 2000)

    def createActions(self, window): pass

    def after(self, fn, delay=300):
        def run():
            try:
                if hasattr(self, 'c') and (self.c.input_busy() or self.c._brush_change):
                    self.after(fn, 100); return
                (ROOT/'phase.json').write_text(json.dumps({'phase':fn.__name__, 'completed':self.result}))
                fn()
            except Exception:
                self.result.update(result='fail', traceback=traceback.format_exc()); self.finish()
        QTimer.singleShot(delay, run)

    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows():
            window.activate(); QApplication.setActiveWindow(window.qwindow())
        if not self.k.activeDocument() or not self.k.activeWindow().qwindow().isVisible():
            self.tries += 1; assert self.tries < 300; self.after(self.start); return
        self.window = self.k.activeWindow(); self.window.activate()
        QApplication.setActiveWindow(self.window.qwindow())
        self.view = self.window.activeView(); self.doc = self.view.document(); self.source = self.doc.activeNode()
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        image = QImage(900,900,QImage.Format.Format_ARGB32); image.fill(QColor('white'))
        painter = QPainter(image); painter.setPen(QPen(QColor('black'),8))
        painter.drawLine(110,180,600,180); painter.drawLine(170,300,550,500); painter.end()
        self.source.setPixelData(QByteArray(image.constBits().asstring(image.sizeInBytes())),0,0,900,900)
        self.doc.refreshProjection(); self.doc.waitForDone()
        self.original = bytes(self.source.pixelData(0,0,900,900))
        self.open_dialog()

    def open_dialog(self):
        from linework.vectorize import open_vectorizer
        self.doc.setActiveNode(self.source); self.source.setVisible(True)
        self.dialog = open_vectorizer(); assert self.dialog
        self.deadline = time.monotonic()+90; self.after(self.preview)

    def preview(self):
        if self.dialog.worker or not self.dialog.strokes:
            assert time.monotonic() < self.deadline, self.dialog.info.text()
            self.after(self.preview); return
        assert len(self.dialog.strokes) == 2, len(self.dialog.strokes)
        self.dialog.native_brush.setChecked(bool(self.mode))
        self.dialog.apply_button.click(); self.after(self.converted)

    def converted(self):
        if self.dialog._applying:
            assert time.monotonic() < self.deadline, self.dialog.info.text()
            self.after(self.converted); return
        from linework.tools import current_controller
        from linework.storage import read_layer
        self.c = current_controller(self.window); self.c.poll()
        assert self.c.layer and self.c.overlay and not self.c._error, (self.c.status.text(), self.c.active, self.c.binding, self.doc.activeNode().name(), self.dialog.info.text())
        layer = self.c.layer
        assert layer.type() == 'paintlayer' and layer.isPinnedToTimeline()
        strokes = read_layer(self.doc,layer)
        assert len(strokes) == 2 and all(bool(s.brush) == bool(self.mode) for s in strokes), (len(strokes), [bool(s.brush) for s in strokes], self.c.status.text(), self.dialog.info.text())
        assert bytes(self.source.pixelData(0,0,900,900)) == self.original
        assert sum(bytes(layer.projectionPixelData(200,170,80,20))[3::4]) > 1000
        self.layers.append((layer.uniqueId(), [s.data() for s in strokes]))
        self.result['native_brush_vectorization' if self.mode else 'smooth_vectorization'] = 'pass'
        from linework.animation import call
        call('frame_action', layer, 2, 0, 5)
        self.doc.setCurrentTime(5); self.doc.waitForDone(); self.c.poll()
        assert [s.data() for s in read_layer(self.doc,layer)] == self.layers[-1][1]
        self.result['vectorized_frame_duplicates_'+str(self.mode)] = 'pass'
        self.mode += 1
        if self.mode < 2:
            self.doc.setCurrentTime(0); self.after(self.open_dialog); return
        assert not self.doc.rootNode().findChildNodes('',True,False,'vectorlayer')
        path = ROOT/'examples/unified-vectorized.kra'; assert self.doc.saveAs(str(path))
        self.loaded = self.k.openDocument(str(path)); assert self.loaded
        self.loaded.waitForDone()
        for uid, expected in self.layers:
            assert [s.data() for s in read_layer(self.loaded,self.loaded.nodeByUniqueID(uid))] == expected
        self.result['both_vectorized_layers_reopen_with_editable_frames'] = 'pass'
        # libkis openDocument without addView leaves a headless document in
        # KisPart. Dispose it while QApplication and its wait broker are alive.
        self.loaded.close()
        self.k.action('linework_new').trigger()
        self.after(self.new_layer_checked)

    def new_layer_checked(self):
        from linework.tools import current_controller
        from linework.animation import descriptor
        from linework.storage import read_layer
        self.c = current_controller(self.window); self.c.poll()
        assert self.c.layer and self.c.overlay and self.c.layer.type() == 'paintlayer', self.c.status.text()
        assert self.c.layer.isPinnedToTimeline() and descriptor(self.doc,self.c.layer)['time'] == 0
        assert read_layer(self.doc,self.c.layer) == []
        assert self.doc.activeNode().uniqueId() == self.c.layer.uniqueId()
        self.result['new_layer_menu_creates_same_editable_timeline_backend'] = 'pass'
        self.window.qwindow().grab().save(str(ROOT/'docs/images/unified-vectorize.png'))
        self.result['result'] = 'pass'; self.after(self.finish)

    def finish(self):
        self.result['krita'] = self.k.version()
        (ROOT/'docs/validation/unified-vectorize.json').write_text(json.dumps(self.result, indent=2))
        for doc in self.k.documents(): doc.setModified(False)
        self.k.activeWindow().qwindow().close(); QTimer.singleShot(300, QApplication.instance().quit)


Krita.instance().addExtension(Probe(Krita.instance()))
