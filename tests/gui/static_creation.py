# SPDX-License-Identifier: GPL-3.0-or-later
"""Static mode: new layer, real brush input and both raster vectorizers."""
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
        self.k.action('linework_static_mode').setChecked(True)
        assert self.k.readSetting('linework','layer_mode','animation')=='static'
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        image = QImage(900,900,QImage.Format.Format_ARGB32); image.fill(QColor('white'))
        painter = QPainter(image); painter.setPen(QPen(QColor('black'),8))
        painter.drawLine(110,180,600,180); painter.drawLine(170,300,550,500); painter.end()
        self.source.setPixelData(QByteArray(image.constBits().asstring(image.sizeInBytes())),0,0,900,900)
        self.doc.refreshProjection(); self.doc.waitForDone()
        self.original = bytes(self.source.pixelData(0,0,900,900))
        self.k.action('linework_new').trigger()
        self.after(self.new_layer_ready,600)

    def new_layer_ready(self):
        from linework.tools import current_controller,select_tool
        from linework.storage import read_layer
        self.c=current_controller(self.window);self.c.poll()
        assert self.c.layer and self.c.layer.type()=='vectorlayer'
        assert read_layer(self.doc,self.c.layer)==[]
        self.result['static_mode_new_layer_is_vector']='pass'
        select_tool(0);self.after(self.draw)

    def draw(self):
        from linework.qt import QPointF,QMouseEvent,QEvent,Qt
        self.c.overlay.sync_transform()
        for kind,x in ((QEvent.Type.MouseButtonPress,150),(QEvent.Type.MouseMove,300),(QEvent.Type.MouseButtonRelease,300)):
            pos=self.c.overlay.image_to_widget.map(QPointF(x,650))
            event=QMouseEvent(kind,pos,Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.c.native_widget,event)
        self.after(self.drawn,700)

    def drawn(self):
        from linework.storage import read_layer
        assert self.c.layer.type()=='vectorlayer' and not self.c._error,self.c.status.text()
        assert len(read_layer(self.doc,self.c.layer))==1
        assert sum(bytes(self.c.layer.projectionPixelData(180,640,80,20))[3::4])>1000
        self.result['static_mode_brush_input_is_editable_and_painted']='pass'
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
        assert layer.type() == 'vectorlayer'
        strokes = read_layer(self.doc,layer)
        assert len(strokes) == 2 and all(bool(s.brush) == bool(self.mode) for s in strokes), (len(strokes), [bool(s.brush) for s in strokes], self.c.status.text(), self.dialog.info.text())
        assert bytes(self.source.pixelData(0,0,900,900)) == self.original
        assert sum(bytes(layer.projectionPixelData(200,170,80,20))[3::4]) > 1000
        self.layers.append((layer.uniqueId(), [s.data() for s in strokes]))
        self.result['native_brush_vectorization' if self.mode else 'smooth_vectorization'] = 'pass'
        self.mode += 1
        if self.mode < 2:
            self.after(self.open_dialog); return
        assert len(self.doc.rootNode().findChildNodes('',True,False,'vectorlayer'))==3
        path = ROOT/'examples/static-created-vectorized.kra'; assert self.doc.saveAs(str(path))
        self.loaded = self.k.openDocument(str(path)); assert self.loaded
        self.loaded.waitForDone()
        for uid, expected in self.layers:
            assert [s.data() for s in read_layer(self.loaded,self.loaded.nodeByUniqueID(uid))] == expected
        self.result['both_static_vectorized_layers_reopen_editable'] = 'pass'
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
        assert self.c.layer and self.c.overlay and self.c.layer.type() == 'vectorlayer', self.c.status.text()
        assert descriptor(self.doc,self.c.layer) is None
        assert read_layer(self.doc,self.c.layer) == []
        assert self.doc.activeNode().uniqueId() == self.c.layer.uniqueId()
        self.result['new_layer_menu_retains_static_default']='pass'
        self.k.action('linework_static_mode').setChecked(False)
        assert self.k.readSetting('linework','layer_mode','static')=='animation'
        self.k.action('linework_new').trigger();self.after(self.animation_checked)

    def animation_checked(self):
        from linework.tools import current_controller
        from linework.animation import descriptor
        from linework.storage import read_layer
        self.c=current_controller(self.window);self.c.poll()
        assert self.c.layer and self.c.layer.type()=='paintlayer' and self.c.layer.isPinnedToTimeline()
        assert descriptor(self.doc,self.c.layer)['time']==0 and read_layer(self.doc,self.c.layer)==[]
        self.result['disabling_static_mode_restores_animation_default']='pass'
        self.window.qwindow().grab().save(str(ROOT/'docs/images/static-creation.png'))
        self.result['result'] = 'pass'; self.after(self.finish)

    def finish(self):
        self.result['krita'] = self.k.version()
        (ROOT/'docs/validation/static-creation.json').write_text(json.dumps(self.result, indent=2))
        for doc in self.k.documents(): doc.setModified(False)
        self.k.activeWindow().qwindow().close(); QTimer.singleShot(300, QApplication.instance().quit)


Krita.instance().addExtension(Probe(Krita.instance()))
