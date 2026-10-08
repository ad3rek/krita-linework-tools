# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic raster-to-Linework conversion inside Krita."""
import copy
import ctypes
import time
from PyQt5 import sip
from PyQt5.QtCore import Qt,QThread,QTimer,QRect,QRectF,QPointF,pyqtSignal
from PyQt5.QtGui import QImage,QPainter,QColor
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,
    QSpinBox,QDoubleSpinBox,QCheckBox,QLabel,QPushButton,QProgressBar,QMessageBox)
from krita import Krita
from .native_brush import load_library,NativeBrushRenderer,capture_brush
from .tracing import TraceEngine,result_strokes
from .editor import painter_path
from .storage import write_layer
from .tools import select_tool,current_controller
from .model import History


def layer_snapshot(document,layer):
    if layer is None or layer.type() not in ('paintlayer','filelayer'):
        raise ValueError('Selecione uma camada raster para vetorizar.')
    bounds=layer.bounds().intersected(QRect(0,0,document.width(),document.height()))
    if bounds.isEmpty():raise ValueError('Esta camada está vazia dentro do canvas.')
    if bounds.width()*bounds.height()>32000000:
        raise ValueError('A área desenhada excede 32 milhões de pixels. Divida-a em camadas menores.')
    lib=load_library()
    lib.linework_layer_snapshot.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)]
    lib.linework_layer_snapshot.restype=ctypes.c_void_p
    lib.linework_preview_pixels.argtypes=[ctypes.c_void_p];lib.linework_preview_pixels.restype=ctypes.c_void_p
    lib.linework_preview_delete.argtypes=[ctypes.c_void_p]
    geometry=(ctypes.c_int*4)();handle=lib.linework_layer_snapshot(sip.unwrapinstance(layer),geometry)
    if not handle:raise ValueError('Não foi possível ler a camada raster.')
    try:
        x,y,w,h=geometry
        pixels=ctypes.string_at(lib.linework_preview_pixels(handle),w*h*4)
        image=QImage(pixels,w,h,QImage.Format_ARGB32).copy()
        return image,(x,y)
    finally:lib.linework_preview_delete(handle)


class TraceWorker(QThread):
    def __init__(self,pixels,width,height,offset,mode,threshold,noise,accuracy,maximum_width,preserve_color,opacity,parent):
        super().__init__(parent);self.engine=TraceEngine();self.pixels=pixels
        self.args=(width,height,mode,threshold,noise,10-accuracy,maximum_width,preserve_color);self.offset=offset
        self.opacity=opacity;self.cancelled=False;self.outcome=None
        self.preview_paths=[]
    def cancel(self):self.cancelled=True;self.engine.cancel()
    def run(self):
        try:
            begin=time.perf_counter();raw=self.engine.run(self.pixels,*self.args)
            strokes=result_strokes(raw,self.offset,opacity=self.opacity,cancel=lambda:self.cancelled)
            for stroke in strokes:
                if self.cancelled:raise InterruptedError('Vetorização cancelada.')
                path=painter_path(stroke);color=QColor(stroke.color)
                self.preview_paths.append((path,color,stroke.opacity,path.boundingRect()))
            self.outcome=(strokes,time.perf_counter()-begin,None)
        except Exception as exc:self.outcome=([],0,exc)


class Preview(QLabel):
    zoomChanged=pyqtSignal(float)

    def __init__(self,parent):
        super().__init__(parent);self.setMinimumSize(480,300)
        self.source=QImage();self.paths=None;self.opacity=1.;self.document_offset=(0,0)
        self.mode=0;self._scale=1.;self._origin=QPointF();self._fit=True;self._drag=None
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('Roda do mouse: zoom · Arraste: mover · Duplo clique: ajustar à janela')

    def extent(self):
        return QPointF(self.source.width()*(2 if self.mode==2 else 1)+(8 if self.mode==2 else 0),self.source.height())

    def fit_scale(self):
        size=self.extent()
        return min(self.width()/max(1.,size.x()),self.height()/max(1.,size.y()))

    def set_content(self,source,opacity,paths,document_offset,mode):
        # Keep the inspected location when switching between the comparison panels.
        center=QPointF(self.rect().center());point=(center-self._origin)/self._scale
        result=self.mode==0 or (self.mode==2 and point.x()>=self.source.width()+8)
        if self.mode==2 and result:
            point.setX(point.x()-self.source.width()-8)
        if mode==2 and result:
            point.setX(point.x()+source.width()+8)
        self.source=source;self.opacity=opacity;self.paths=paths;self.document_offset=document_offset;self.mode=mode
        if self._fit:self.fit_to_view()
        else:self._origin=center-point*self._scale;self.update()

    def fit_to_view(self):
        self._fit=True;self._scale=self.fit_scale()
        self._origin=(QPointF(self.width(),self.height())-self.extent()*self._scale)/2
        self.zoomChanged.emit(self._scale);self.update()

    def zoom_by(self,factor,position=None):
        if self.source.isNull():return
        anchor=QPointF(self.rect().center()) if position is None else QPointF(position)
        lower=max(.0001,min(.01,self.fit_scale()/10))
        scale=max(lower,min(max(32.,self.fit_scale()),self._scale*factor))
        self._origin=anchor-(anchor-self._origin)*(scale/self._scale)
        self._scale=scale;self._fit=False;self.zoomChanged.emit(scale);self.update()

    def wheelEvent(self,event):
        delta=event.angleDelta().y() or event.pixelDelta().y()
        if delta:self.zoom_by(2.**(max(-960,min(960,delta))/480),event.position())
        event.accept()

    def mousePressEvent(self,event):
        if event.button() in (Qt.LeftButton,Qt.MiddleButton):
            self._drag=event.localPos();self.setCursor(Qt.ClosedHandCursor);event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._drag is not None:
            self._origin+=event.localPos()-self._drag;self._drag=event.localPos()
            self._fit=False;self.update();event.accept()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button() in (Qt.LeftButton,Qt.MiddleButton):
            self._drag=None;self.setCursor(Qt.OpenHandCursor);event.accept()
        else:super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:
            self._drag=None;self.setCursor(Qt.OpenHandCursor);self.fit_to_view();event.accept()
        else:super().mouseDoubleClickEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self._fit:self.fit_to_view()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),self.palette().dark())
        if self.source.isNull():return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform,self._scale<1)
        visible=QRectF(-self._origin.x()/self._scale,-self._origin.y()/self._scale,
                       self.width()/self._scale,self.height()/self._scale)
        painter.translate(self._origin);painter.scale(self._scale,self._scale)
        box=QRectF(0,0,self.source.width(),self.source.height())
        for x,result in ([(0,False),(self.source.width()+8,True)] if self.mode==2 else [(0,self.mode==0)]):
            painter.save();painter.translate(x,0);painter.setClipRect(box);painter.fillRect(box,Qt.white)
            if result and self.paths is not None:
                painter.translate(-self.document_offset[0],-self.document_offset[1]);painter.setPen(Qt.NoPen)
                area=visible.translated(self.document_offset[0]-x,self.document_offset[1])
                for path,color,opacity,bounds in self.paths:
                    if not bounds.intersects(area):continue
                    painter.setBrush(color);painter.setOpacity(opacity);painter.drawPath(path)
            else:
                painter.setOpacity(self.opacity);painter.drawImage(0,0,self.source)
            painter.restore()


class VectorizeDialog(QDialog):
    def __init__(self,window):
        super().__init__(window.qwindow());self.setWindowTitle('Vetorizar camada em Linework')
        self.setWindowModality(Qt.ApplicationModal);self.setAttribute(Qt.WA_DeleteOnClose)
        self.window=window;self.view=window.activeView();self.document=self.view.document()
        self.source=self.document.activeNode();self.snapshot,self.offset=layer_snapshot(self.document,self.source)
        self.setMinimumWidth(640);self.worker=None;self.strokes=None;self._reject_pending=False
        self._applying=False;self._apply_index=0;self.renderer=None;self._apply_cancel=False
        self._native_svg={}
        self._geometry=(self.document.width(),self.document.height(),self.document.xRes(),self.document.yRes())
        body=QVBoxLayout(self);body.addWidget(QLabel('Origem: '+self.source.name()))
        body.addWidget(QLabel('Motor: OpenToonz · linha central'))
        form=QFormLayout();body.addLayout(form)
        self.mode=QComboBox();self.mode.addItems(['Traços sobre fundo claro','Alfa / fundo transparente'])
        border=[self.snapshot.pixelColor(x,y).alpha() for x,y in
            ((0,0),(self.snapshot.width()-1,0),(0,self.snapshot.height()-1),
             (self.snapshot.width()-1,self.snapshot.height()-1))]
        self.mode.setCurrentIndex(1 if sum(a<16 for a in border)>=3 else 0)
        form.addRow('Detectar',self.mode)
        self.threshold=QSpinBox();self.threshold.setRange(1,254);self.threshold.setValue(128 if self.mode.currentIndex() else 170)
        form.addRow('Limiar',self.threshold)
        self.noise=QSpinBox();self.noise.setRange(0,10000);self.noise.setValue(12);self.noise.setSuffix(' px²')
        form.addRow('Remover manchas menores que',self.noise)
        self.accuracy=QDoubleSpinBox();self.accuracy.setRange(1,10);self.accuracy.setValue(9.5)
        self.accuracy.setToolTip('Precisão do OpenToonz: maior valor preserva mais detalhes. Penalidade = 10 − precisão.')
        self.smoothing=self.accuracy  # Compatibility with earlier integration probes.
        form.addRow('Precisão',self.accuracy)
        self.maximum_width=QDoubleSpinBox();self.maximum_width.setRange(.1,2000);self.maximum_width.setValue(200);self.maximum_width.setSuffix(' px')
        self.maximum_width.setToolTip('Limite do OpenToonz para a largura total. Regiões maiores podem gerar contornos.')
        form.addRow('Espessura máxima',self.maximum_width)
        self.preserve_color=QCheckBox('Preservar cor e transparência do bitmap');self.preserve_color.setChecked(True)
        self.preserve_color.setToolTip('Aplica a aparência às curvas prontas. Desmarcado usa preto, como o OpenToonz em raster RGB.')
        form.addRow(self.preserve_color)
        self.native_brush=QCheckBox('Usar o preset atual do Krita no resultado')
        self.native_brush.setToolTip('A prévia mostra a geometria. O preset interpreta a pressão ao criar a camada.')
        form.addRow(self.native_brush)
        self.native_hint=QLabel('Prévia geométrica; o preset será aplicado ao criar a camada.')
        self.native_hint.setWordWrap(True);self.native_hint.hide();form.addRow(self.native_hint)
        self.native_brush.toggled.connect(self.native_hint.setVisible)
        self.hide_source=QCheckBox('Ocultar a camada raster depois de converter');self.hide_source.setChecked(True)
        form.addRow(self.hide_source)
        self.preview=Preview(self);body.addWidget(self.preview,1)
        self.compare=QComboBox();self.compare.addItems(['Resultado','Original','Comparar lado a lado'])
        navigation=QHBoxLayout();body.addLayout(navigation);navigation.addWidget(self.compare,1)
        self.zoom_out=QPushButton('−');self.zoom_in=QPushButton('+');self.fit_button=QPushButton('Ajustar')
        self.zoom_label=QLabel();self.zoom_label.setMinimumWidth(56);self.zoom_label.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        for button,tip in ((self.zoom_out,'Diminuir zoom'),(self.zoom_in,'Aumentar zoom'),(self.fit_button,'Ajustar à janela')):
            button.setAutoDefault(False);button.setToolTip(tip);navigation.addWidget(button)
        self.zoom_out.setMaximumWidth(32);self.zoom_in.setMaximumWidth(32);navigation.addWidget(self.zoom_label)
        self.zoom_out.clicked.connect(lambda:self.preview.zoom_by(1/1.25))
        self.zoom_in.clicked.connect(lambda:self.preview.zoom_by(1.25));self.fit_button.clicked.connect(self.preview.fit_to_view)
        self.preview.zoomChanged.connect(lambda scale:self.zoom_label.setText('{:.0f}%'.format(scale*100)))
        self.compare.currentIndexChanged.connect(self.draw_preview)
        self.compare_hint=QLabel('Original à esquerda · Linework à direita');self.compare_hint.hide();body.addWidget(self.compare_hint)
        self.compare.currentIndexChanged.connect(lambda index:self.compare_hint.setVisible(index==2))
        self.info=QLabel('A camada original será preservada.');self.info.setWordWrap(True);body.addWidget(self.info)
        self.progress=QProgressBar();self.progress.hide();body.addWidget(self.progress)
        row=QHBoxLayout();body.addLayout(row)
        self.preview_button=QPushButton('Atualizar prévia');self.apply_button=QPushButton('Criar camada Linework')
        self.apply_button.setEnabled(False);self.cancel_button=QPushButton('Cancelar')
        for button in (self.preview_button,self.apply_button,self.cancel_button):row.addWidget(button)
        self.preview_button.clicked.connect(self.start_preview);self.apply_button.clicked.connect(self.apply)
        self.cancel_button.clicked.connect(self.reject)
        self.preserve_color.toggled.connect(self.invalidate)
        for control in (self.mode,self.threshold,self.noise,self.accuracy,self.maximum_width):
            signal=control.currentIndexChanged if control==self.mode else control.valueChanged
            signal.connect(self.invalidate)
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.poll_progress)
        self.paint_timer=QTimer(self);self.paint_timer.setSingleShot(True);self.paint_timer.timeout.connect(self.paint_next)
        from PyQt5.QtWidgets import QApplication
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self._result_paths=None;self.draw_preview()
        QTimer.singleShot(0,self.start_preview)

    def invalidate(self):
        self.strokes=None;self.apply_button.setEnabled(False)
        if self.worker:self.worker.cancel()
        self.info.setText('Atualize a prévia para aplicar os novos ajustes.')

    def busy(self,value):
        for control in (self.mode,self.threshold,self.noise,self.accuracy,self.maximum_width,self.preserve_color,self.native_brush,self.hide_source,self.preview_button):
            control.setEnabled(not value)
        self.apply_button.setEnabled(not value and bool(self.strokes))
        self.progress.setVisible(value)

    def start_preview(self):
        if self.worker or self._applying:return
        self.busy(True);self.progress.setValue(0);self.info.setText('Extraindo linhas e espessura…')
        bits=self.snapshot.constBits();bits.setsize(self.snapshot.byteCount())
        try:
            self.worker=TraceWorker(bytes(bits),self.snapshot.width(),self.snapshot.height(),self.offset,
                self.mode.currentIndex(),self.threshold.value(),self.noise.value(),self.accuracy.value(),self.maximum_width.value(),self.preserve_color.isChecked(),
                self.source.opacity()/255.0,self)
        except Exception as exc:
            self.busy(False);self.info.setText(str(exc));return
        self.worker.finished.connect(self.preview_finished);self.timer.start();self.worker.start()

    def poll_progress(self):
        if self.worker:self.progress.setValue(self.worker.engine.progress())

    def preview_finished(self):
        worker,self.worker=self.worker,None;self.timer.stop()
        self.strokes,elapsed,error=worker.outcome
        if not error:self._result_paths=worker.preview_paths
        worker.engine.close();worker.deleteLater();self.busy(False)
        if self._reject_pending:super().reject();return
        if error:self.info.setText(str(error));return
        count=sum(len(s.points) for s in self.strokes)
        self.info.setText('{} traços · {} pontos · {:.2f} s'.format(len(self.strokes),count,elapsed) if self.strokes
                          else 'Nenhum traço encontrado. Ajuste o modo de detecção ou o limiar.')
        self.draw_preview()

    def draw_preview(self):
        self.preview.set_content(self.snapshot,self.source.opacity()/255.0,
            self._result_paths,self.offset,self.compare.currentIndex())

    def apply(self):
        if not self.strokes or self.worker or self._applying:return
        if self.source.parentNode() is None or self._geometry!=(self.document.width(),self.document.height(),self.document.xRes(),self.document.yRes()):
            self.info.setText('A origem ou o tamanho do documento mudou. Abra a conversão novamente.');return
        self._applying=True;self._apply_cancel=False;self.busy(True);self.progress.setValue(0)
        try:
            for s in self.strokes:s.brush=None
            if self.native_brush.isChecked():
                brush=capture_brush(self.view)
                for s in self.strokes:s.brush=copy.deepcopy(brush)
                self._native_svg={};self.renderer=NativeBrushRenderer(self.view);self._apply_index=0;self.paint_timer.start(0)
            else:self.commit_layer()
        except Exception as exc:self.apply_error(exc)

    def paint_next(self):
        if self._apply_cancel:self.apply_error(InterruptedError('Conversão cancelada.'));return
        try:
            if self._apply_index>=len(self.strokes):self.commit_layer();return
            self.info.setText('Aplicando pincel: {} de {}'.format(self._apply_index+1,len(self.strokes)))
            stroke=self.strokes[self._apply_index]
            self._native_svg[stroke.uid]=self.renderer.svg_image(stroke);self._apply_index+=1
            self.progress.setValue(round(self._apply_index*100/len(self.strokes)));self.paint_timer.start(0)
        except Exception as exc:self.apply_error(exc)

    def commit_layer(self):
        layer=None
        source_visible=self.source.visible()
        try:
            self.document.setActiveNode(self.source);select_tool(3);controller=current_controller(self.window)
            if controller is None:raise ValueError('Não foi possível ativar Linework nesta visualização.')
            layer=controller.create_native_layer(self.document)
            layer.setName('Linework — '+self.source.name())
            native_renderer=None
            if self.renderer:
                class Prepared:
                    def __init__(self,images):self.images=images
                    def svg_image(self,stroke):return self.images[stroke.uid]
                native_renderer=Prepared(self._native_svg)
            write_layer(self.document,layer,self.strokes,native_renderer)
            if self.hide_source.isChecked():self.source.setVisible(False)
            self.document.setModified(True);self.document.refreshProjection();self.document.waitForDone()
            controller.document=self.document;controller.layer=layer
            controller._selection_pending=True;controller._selection_deadline=time.monotonic()+3
            controller.select_native_layer()
            controller.poll()
            if controller.overlay and controller.layer and controller.layer.uniqueId()==layer.uniqueId():
                overlay=controller.overlay
                overlay.history=History([]);overlay.history.commit(overlay.strokes)
                overlay.conversion_origin=(self.source,source_visible,self.hide_source.isChecked(),
                                           {s.uid for s in overlay.strokes},False)
            self._applying=False
            if self.renderer:self.renderer.close();self.renderer=None
            super().accept()
        except Exception:
            if layer:layer.remove()
            self.document.setActiveNode(self.source)
            raise

    def apply_error(self,error):
        self._applying=False
        if self.renderer:self.renderer.close();self.renderer=None
        self.busy(False);self.info.setText(str(error))
        if self._reject_pending:super().reject()

    def reject(self):
        if self.worker:
            self._reject_pending=True;self.worker.cancel();self.info.setText('Cancelando…');return
        if self._applying:
            self._reject_pending=True;self._apply_cancel=True;return
        super().reject()

    def closeEvent(self,event):
        if self.worker or self._applying:self.reject();event.ignore()
        else:super().closeEvent(event)

    def shutdown(self):
        self.paint_timer.stop()
        if self.worker:self.worker.cancel();self.worker.wait();self.worker.engine.close()
        if self.renderer:self.renderer.close();self.renderer=None


def open_vectorizer(window=None):
    if window is None or sip.isdeleted(window):
        window=Krita.instance().activeWindow()
    if window is None:
        return None
    parent=window.qwindow()
    if parent is None or sip.isdeleted(parent):
        return None
    view=window.activeView()
    if view is None or view.document() is None:
        QMessageBox.information(parent,'Linework','Abra uma imagem e selecione uma camada raster.');return None
    try:
        dialog=VectorizeDialog(window);dialog.show();return dialog
    except Exception as exc:
        QMessageBox.information(parent,'Linework',str(exc));return None
