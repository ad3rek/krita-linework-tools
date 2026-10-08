# SPDX-License-Identifier: GPL-3.0-or-later
"""Native tool options and editable input on Krita's actual canvas widget."""
import copy
import math
import time
from collections import deque
from PyQt5.QtCore import Qt, QEvent, QPointF, QTimer, QRectF, QEventLoop, pyqtSignal
from PyQt5 import sip
from PyQt5.QtGui import (QColor, QIcon, QPixmap, QPainter, QPainterPath, QPen,
                        QMouseEvent, QTabletEvent, QKeyEvent)
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QDoubleSpinBox, QFileDialog, QComboBox, QProgressBar, QHBoxLayout)
from krita import Krita
from .editor import LineworkCanvas, painter_path
from .model import Point, samples, svg, handle_vector, geometry_key, set_point_thickness
from .storage import read_layer, write_layer, layer_id
from .native_brush import (NativeBrushRenderer, capture_brush, set_preview_hidden,
                          begin_edit_session, end_edit_session, point_thickness, ensure_thickness, native_busy)
from .native_smoothing import NativeSmoother, SmoothingOptions
from .preview import SavedAppearanceCache


class MixedSpinBox(QDoubleSpinBox):
    sameValueCommitted = pyqtSignal(float)

    def __init__(self):
        super().__init__(); self.mixed = False; self._edited = False; self._typed = ''; self._suffix = ''
        self.lineEdit().setPlaceholderText('Vários')
        self.lineEdit().textEdited.connect(self.text_edited)
        self.valueChanged.connect(self.value_changed)
        self.editingFinished.connect(self.edit_finished)

    def text_edited(self, text): self._edited = True; self._typed = text
    def textFromValue(self, value):
        return '' if getattr(self, 'mixed', False) else super().textFromValue(value)
    def value_changed(self, value):
        self.mixed = False; self._edited = False; super().setSuffix(self._suffix)

    def setSuffix(self, suffix):
        self._suffix = suffix; super().setSuffix(suffix)

    def set_mixed(self, value):
        self.mixed = value; self._edited = False
        super().setSuffix('' if value else self._suffix)
        if value: self.lineEdit().clear()
        else: self.lineEdit().setText(self.textFromValue(self.value())+self.suffix())

    def edit_finished(self):
        if self._edited and self._typed.strip():
            self._edited = False; self.mixed = False
            self.sameValueCommitted.emit(self.value())
        elif self.mixed: self.lineEdit().clear()

    def stepBy(self, steps):
        mixed, before = self.mixed, self.value()
        self.set_mixed(False); super().stepBy(steps)
        if mixed and self.value() == before: self.sameValueCommitted.emit(self.value())


class NativeCanvasOverlay(LineworkCanvas):
    """Transparent paint aid; the document remains rendered by Krita itself."""
    def __init__(self, view, native_widget, strokes, source_layer=None):
        doc = view.document()
        super().__init__(doc.width(), doc.height(), strokes, native_widget)
        self.view = view
        self.renderer = NativeBrushRenderer(view)
        self.smoother = None
        self._finishing = False
        self._draw_session = None
        self.smoothing_options = None
        self.smoothing_timer = QTimer(self)
        self.smoothing_timer.setInterval(16)
        self.smoothing_timer.timeout.connect(self.drain_smoothing)
        self.source_layer = source_layer
        self.saved_appearances = SavedAppearanceCache()
        self._edit_original = None
        self._edit_session = None
        self._edit_committing = False
        self.conversion_origin = None
        self.native_preview = None
        self.native_previews = {}
        self._preview_keys = {}
        self._preview_cursor = 0
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(16)
        self.preview_timer.timeout.connect(self.refresh_native_preview)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setGeometry(native_widget.rect())
        self.sync_transform()
        self.show()
        self.raise_()

    def sync_transform(self):
        inverse, ok = self.view.flakeToImageTransform().inverted()
        if not ok:
            raise ValueError("Transformação do canvas inválida.")
        self.image_to_widget = inverse * self.view.flakeToCanvasTransform()
        self.widget_to_image, ok = self.image_to_widget.inverted()
        if not ok:
            raise ValueError("Transformação do canvas inválida.")
        self.zoom = math.hypot(self.image_to_widget.m11(), self.image_to_widget.m12())

    def local_point(self, pos, pressure=1):
        self.sync_transform()
        point = self.widget_to_image.map(pos)
        return Point(point.x(), point.y(), pressure)

    def setFocus(self, reason=Qt.MouseFocusReason):
        # Krita identifies its active view from canvas focus. Never focus the
        # transparent child, which would detach the active node from libkis.
        self.parentWidget().setFocus(reason)

    def begin(self, pos, pressure, button=Qt.LeftButton, modifiers=Qt.NoModifier):
        # Canvas focus remains in Krita. Pan and zoom are handled by Krita.
        if self.mode == 'pen' and button == Qt.LeftButton and self.draft:
            # A lost release must not let the next press replace a drawn path
            # or leave its native smoothing/preview sessions running.
            self.finish_draft()
        if button == Qt.LeftButton and self.mode in ("pen", "curve", "line") and self.draft is None:
            self.renderer.load_bridge()
            self.defaults["brush"] = capture_brush(self.view)
            self.defaults["width"] = self.view.brushSize()
            self.defaults["opacity"] = self.view.paintingOpacity()
            self.defaults["color"] = self.view.foregroundColor().colorForCanvas(self.view.canvas()).name()
            self.native_preview = None
        super().begin(pos, pressure, button, modifiers)
        if self.mode == "pen" and self.draft:
            self.draft._live_points = []
            self.smoother = NativeSmoother(self.renderer, self.smoothing_options, self.draft.points[0])
            self.renderer.start_live(self.draft)
            self.smoothing_timer.start()
            # A no-paint stroke on the document makes save/clone requests
            # finish this tool before they snapshot its projection.
            self._draw_session = begin_edit_session(self.view.document().activeNode())
        if self.drag in ("point", "stroke", "pressure", "handle"):
            self.begin_edit_preview()
        else:
            self.queue_native_preview()

    def begin_edit_preview(self):
        affected = [self.active_stroke()] if self.drag == 'handle' else self.selected_strokes()
        if not affected or self.source_layer is None:
            return
        self._edit_original = {s.uid: copy.deepcopy(s) for s in affected}
        self.native_preview = None; self.native_previews = {}; self._preview_keys = {}
        try:
            for stroke in affected:
                cached = self.saved_appearances.get(self.view.document(), self.source_layer, stroke)
                if cached:
                    self.native_previews[stroke.uid] = cached
                    self.native_preview = (stroke.uid, *cached)
                    self._preview_keys[stroke.uid] = self.preview_key(stroke)
                if not set_preview_hidden(self.source_layer, stroke.uid, True):
                    raise ValueError("Não foi possível ocultar a aparência original do traço.")
            self._edit_session = begin_edit_session(self.source_layer)
        except Exception:
            self.restore_edit_preview(cancel=True); raise
        self.update()

    def restore_edit_preview(self, cancel=False):
        original, self._edit_original = self._edit_original, None
        if original is None:
            return
        self.preview_timer.stop()
        self.native_preview = None
        self.native_previews = {}; self._preview_keys = {}
        self.drag = None
        self._edit_committing = False
        session, self._edit_session = self._edit_session, None
        end_edit_session(session)
        if cancel:
            for i, stroke in enumerate(self.strokes):
                if stroke.uid in original:
                    self.strokes[i] = original[stroke.uid]
        if self.source_layer:
            for uid in original: set_preview_hidden(self.source_layer, uid, False)
        if not sip.isdeleted(self):
            self.update()

    def commit(self):
        original = self._edit_original
        if original and all(s.data() == original[s.uid].data() for s in self.strokes if s.uid in original):
            self.restore_edit_preview(cancel=True)
            return
        try:
            if original:
                for stroke in self.strokes:
                    if stroke.uid in original and stroke.brush:
                        self.renderer.render(stroke)
                self._edit_committing = True
                session, self._edit_session = self._edit_session, None
                end_edit_session(session)
            # Shapes and their SVG stay intact while hidden from the render
            # manager; storage can verify/replace only the edited stroke.
            super().commit()
        finally:
            if original:
                for uid in original: self.saved_appearances.forget(uid)
                self.restore_edit_preview()
            else:
                stroke = self.active_stroke()
                if stroke:
                    self.saved_appearances.forget(stroke.uid)

    def move(self, pos, pressure, modifiers=Qt.NoModifier):
        if self.smoother and self.draft and self.drag == 'pen':
            self.hover_pos = pos
            self.smoother.move(self.local_point(pos, pressure))
            self.drain_smoothing(); return
        super().move(pos, pressure, modifiers)
        if self.draft and self.renderer.stream:
            self.renderer.append_live(self.draft)
        self.queue_native_preview()

    def end(self, pos, pressure):
        if self.smoother and self.draft and self.drag == 'pen':
            self.finish_draft(); self.drag = None
            self.preview_timer.stop(); self.native_preview = None
            return
        self.renderer.end_live()
        super().end(pos, pressure)
        if self.draft is None:
            self.preview_timer.stop()
            self.native_preview = None

    def finish_draft(self):
        if self._finishing:
            return
        self._finishing = True
        try:
            if self.smoother and self.draft:
                self.smoother.finish(self.draft); self.smoother = None
                self.renderer.append_live(self.draft)
                if hasattr(self.draft, '_live_points'): del self.draft._live_points
            self.smoothing_timer.stop()
            self.end_draw_session()
            self.restore_edit_preview(cancel=True)
            self.renderer.end_live()
            super().finish_draft()
        finally:
            self._finishing = False

    def drain_smoothing(self):
        if native_busy(): return
        if self.smoother and self.draft:
            try:
                if self.smoother.take_into(self.draft):
                    self.renderer.append_live(self.draft)
                    self.queue_native_preview(); self.update()
            except Exception as exc:
                self.stop_smoothing(); self.draft = None; self.drag = None
                self.renderer.end_live(); self.message.emit(str(exc))

    def stop_smoothing(self):
        if not sip.isdeleted(self.smoothing_timer): self.smoothing_timer.stop()
        if self.smoother: self.smoother.close(); self.smoother = None
        self.end_draw_session()

    def end_draw_session(self):
        session, self._draw_session = self._draw_session, None
        end_edit_session(session)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._edit_original:
            self.restore_edit_preview(cancel=True)
        if event.key() == Qt.Key_Escape:
            self.stop_smoothing()
            editing = bool(self._edit_original)
            self.restore_edit_preview(cancel=True)
            self.selectedChanged.emit()
            self.renderer.end_live()
            self.preview_timer.stop()
            self.native_preview = None
            if editing:
                self.selectedChanged.emit(); self.update(); return
        super().keyPressEvent(event)

    def undo(self):
        if self._edit_original:
            self.restore_edit_preview(cancel=True)
            self.selectedChanged.emit()
            return
        had_undo = bool(self.history.undo_stack) and self.draft is None
        super().undo()
        if had_undo and self.conversion_origin and not self.history.current and not self.history.undo_stack:
            source, visible, hidden, ids, undone = self.conversion_origin
            if source.parentNode():
                source.setVisible(visible)
                self.view.document().refreshProjection()
            self.conversion_origin = (source, visible, hidden, ids, True)
        self.saved_appearances.clear()

    def redo(self):
        self.restore_edit_preview(cancel=True)
        super().redo()
        if self.conversion_origin:
            source, visible, hidden, ids, undone = self.conversion_origin
            if undone and ids.intersection(s.uid for s in self.strokes):
                if source.parentNode():
                    source.setVisible(False if hidden else visible)
                    self.view.document().refreshProjection()
                self.conversion_origin = (source, visible, hidden, ids, False)
        self.saved_appearances.clear()

    def set_mode(self, mode):
        self.restore_edit_preview(cancel=True)
        super().set_mode(mode)

    def queue_native_preview(self):
        if not self.draft and self.drag not in ("point", "stroke", "pressure", "handle"):
            return
        if not self.preview_timer.isActive():
            self.preview_timer.setInterval(16 if self.renderer.stream else 75)
            self.preview_timer.start()

    def refresh_native_preview(self):
        if native_busy(): return
        if self._edit_original:
            if self.renderer.busy:
                self.preview_timer.start(25); return
            edited = [s for s in self.strokes if s.uid in self._edit_original and s.brush]
            dirty = [s for s in edited if self._preview_keys.get(s.uid) != self.preview_key(s)]
            if not dirty: return
            dirty_ids = {s.uid for s in dirty}
            for offset in range(len(edited)):
                index = (self._preview_cursor+offset) % len(edited)
                if edited[index].uid in dirty_ids:
                    stroke = edited[index]; self._preview_cursor = (index+1) % len(edited); break
            try:
                key = self.preview_key(stroke)
                bounds, image, _ = self.renderer.render(stroke, preview=True)
                self.native_previews[stroke.uid] = (bounds, image)
                self.native_preview = (stroke.uid, bounds, image)
                self._preview_keys[stroke.uid] = key
                if len(dirty) > 1: self.preview_timer.start(25)
                self.update()
            except Exception as exc: self.message.emit(str(exc))
            return
        stroke = self.draft or (self.active_stroke() if self.drag in ("point", "stroke", "pressure", "handle") else None)
        if not stroke or not stroke.brush or not self.isVisible():
            return
        if self.renderer.busy:
            self.preview_timer.start()
            return
        try:
            if self.renderer.stream and self.draft:
                snapshot = self.renderer.live_snapshot()
                if snapshot is None:
                    self.preview_timer.start(16)
                    return
                bounds, image = snapshot
            else:
                bounds, image, _ = self.renderer.render(stroke, preview=True)
            self.native_preview = (stroke.uid, bounds, image)
            self.update()
        except Exception as exc:
            self.message.emit(str(exc))

    def preview_key(self, stroke):
        return geometry_key(stroke), stroke.width, stroke.opacity, stroke.minimum, stroke.taper_start, stroke.taper_end

    def paintEvent(self, event):
        if native_busy(): return
        try:
            self.sync_transform()
        except RuntimeError:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setTransform(self.image_to_widget)
        painter.setClipRect(QRectF(0, 0, self.doc_width, self.doc_height))
        # Only in-progress geometry is painted here. Completed strokes are native SVG.
        stroke = self.active_stroke()
        previews = [s for s in self.strokes if self._edit_original and s.uid in self._edit_original and not self._edit_committing]
        for s in previews+([self.draft] if self.draft else []):
            if s:
                if s.brush:
                    cached = self.native_previews.get(s.uid) if s is not self.draft else (
                        self.native_preview[1:] if self.native_preview and self.native_preview[0] == s.uid else None)
                    if cached:
                        bounds, image = cached
                        painter.drawImage(QRectF(bounds), image)
                    continue
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(s.color))
                painter.setOpacity(s.opacity)
                painter.drawPath(painter_path(s))
        painter.setOpacity(1)
        point_keys = self.selection.point_keys(self.strokes)
        for selected in self.selected_strokes() if self.mode in ("edit", "pressure", "erase") else []:
            center = self.cached_center(selected)
            painter.setPen(QPen(QColor("#39bfff"), 1.2/self.zoom))
            painter.setBrush(Qt.NoBrush)
            if center:
                path = QPainterPath(QPointF(center[0].x, center[0].y))
                for p in center[1:]:
                    path.lineTo(p.x, p.y)
                painter.drawPath(path)
            if selected is stroke and self.mode == "edit" and self.point_index >= 0:
                anchor = stroke.points[self.point_index]
                for side in ("in", "out"):
                    vector = handle_vector(stroke, self.point_index, side)
                    if vector is None:
                        continue
                    control = QPointF(anchor.x+vector[0], anchor.y+vector[1])
                    painter.setPen(QPen(QColor("#39bfff"), 1/self.zoom))
                    painter.drawLine(QPointF(anchor.x, anchor.y), control)
                    painter.setBrush(QColor("#ffbf45") if self.drag == "handle" and self.handle_side == side
                                     else QColor("#e8f6ff"))
                    radius = 3.5/self.zoom
                    painter.drawRect(QRectF(control.x()-radius, control.y()-radius, 2*radius, 2*radius))
            if self.mode == "pressure":
                for i, p in enumerate(selected.points):
                    # Diameter guides use the same editable profile as rendering.
                    tangent = handle_vector(selected, i, "out") or handle_vector(selected, i, "in")
                    if tangent is None or math.hypot(*tangent) < 1e-7:
                        a, b = selected.points[max(0, i-1)], selected.points[min(len(selected.points)-1, i+1)]
                        tangent = b.x-a.x, b.y-a.y
                    length = math.hypot(*tangent)
                    nx, ny = (-tangent[1]/length, tangent[0]/length) if length else (0, 1)
                    radius = (selected.width*selected.minimum+(1-selected.minimum)*point_thickness(selected, i))/2
                    radius = max(6/self.zoom, min(radius, 100/self.zoom))
                    chosen = (selected.uid, i) in point_keys
                    color = QColor("#ffbf45" if chosen else "#39bfff")
                    color.setAlpha(230 if chosen else 130)
                    painter.setPen(QPen(color, (1.5 if chosen else 1)/self.zoom))
                    left, right = QPointF(p.x+nx*radius, p.y+ny*radius), QPointF(p.x-nx*radius, p.y-ny*radius)
                    painter.drawLine(left, right)
                    painter.setBrush(color)
                    for end in (left, right):
                        painter.drawEllipse(end, 2/self.zoom, 2/self.zoom)
            painter.setPen(QPen(QColor("#39bfff"), 1.2/self.zoom))
            for i, p in enumerate(selected.points):
                painter.setBrush(QColor("#ffbf45") if (selected.uid, i) in point_keys else QColor("#e8f6ff"))
                radius = (5 if selected is stroke and i == self.point_index else 3.5)/self.zoom
                painter.drawEllipse(QPointF(p.x, p.y), radius, radius)
            if selected is stroke and self.mode == "pressure" and self.point_index >= 0:
                p = stroke.points[self.point_index]
                location = self.image_to_widget.map(QPointF(p.x, p.y))
                painter.save()
                painter.resetTransform()
                painter.setClipping(False)
                text = "Espessura: {:.1f} px".format(point_thickness(stroke, self.point_index))
                rect = painter.fontMetrics().boundingRect(text).adjusted(-7, -4, 7, 4)
                rect.moveTopLeft((location+QPointF(14, -rect.height()-10)).toPoint())
                rect.moveLeft(max(2, min(rect.left(), self.width()-rect.width()-2)))
                rect.moveTop(max(2, min(rect.top(), self.height()-rect.height()-2)))
                painter.setPen(QPen(self.palette().mid().color(), 1))
                painter.setBrush(self.palette().window())
                painter.drawRoundedRect(QRectF(rect), 4, 4)
                painter.setPen(self.palette().windowText().color())
                painter.drawText(rect, Qt.AlignCenter, text)
                painter.restore()
        if self.drag == 'select':
            rect = QRectF(QPointF(self._selection_start.x, self._selection_start.y),
                          QPointF(self._selection_end.x, self._selection_end.y)).normalized()
            color = self.palette().highlight().color()
            painter.setPen(QPen(color, 1/self.zoom, Qt.DashLine))
            color.setAlpha(35); painter.setBrush(color); painter.drawRect(rect)
        if self.draft and self.mode in ("curve", "line"):
            painter.setPen(QPen(QColor("#39bfff"), 1/self.zoom))
            painter.setBrush(QColor("#e8f6ff"))
            for p in self.draft.points:
                painter.drawEllipse(QPointF(p.x, p.y), 4/self.zoom, 4/self.zoom)
        options = self.smoothing_options
        if self.mode == 'pen' and options and int(options[0]) == 3 and options[6] and self.hover_pos is not None:
            center = (QPointF(self.draft.points[-1].x, self.draft.points[-1].y)
                      if self.draft and self.draft.points else self.widget_to_image.map(self.hover_pos))
            radius = options[5]/self.zoom
            painter.setPen(QPen(self.palette().highlight().color(), 1/self.zoom))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, radius, radius)


class LineworkToolOptions(QWidget):
    def __init__(self, native_widget):
        super().__init__()
        self._canvas = native_widget
        self._window = native_widget.window()
        self.active = False
        self._error = None
        self.mode = "pen"
        self.setWindowTitle("Linework Brush")
        self.overlay = None
        self.native_widget = None
        self.document = None
        self.layer = None
        self.binding = None
        self._writing = False
        self._clearing = False
        self._updating = False
        self._input_depth = 0
        self._pending_input = deque()
        self._replaying_input = False
        self.input_timer = QTimer(self)
        self.input_timer.setSingleShot(True)
        self.input_timer.timeout.connect(self.drain_input)
        self._tablet_until = 0
        self._passing_navigation = False
        self._space = False
        self._selection_pending = False
        self._last_selected = None
        self._last_managed = False
        self._brush_change = None
        self._foreground_color = None
        self._pending_color = None
        self.color_timer = QTimer(self)
        self.color_timer.setSingleShot(True)
        self.color_timer.timeout.connect(self.apply_pending_color)
        self.brush_timer = QTimer(self)
        self.brush_timer.setSingleShot(True)
        self.brush_timer.timeout.connect(self.paint_brush_change)
        self._defaults = dict(width=8, color="#202020", opacity=1, minimum=0, taper_start=0, taper_end=0)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        self.tool_label = QLabel("Linework Brush", self)
        self.tool_label.hide()  # The native tool docker already provides its title.
        self.brush_group = QGroupBox("Pincel")
        brush_layout = QVBoxLayout(self.brush_group)
        self.brush_label = QLabel("Escolha um preset no painel Pincéis do Krita.")
        self.brush_label.setWordWrap(True)
        brush_layout.addWidget(self.brush_label)
        self.stroke_brush_label = QLabel()
        self.stroke_brush_label.setWordWrap(True)
        brush_layout.addWidget(self.stroke_brush_label)
        self.brush_scope = QComboBox()
        self.brush_scope.addItems(["Traços selecionados", "Todos os traços da camada"])
        self.brush_scope.currentIndexChanged.connect(self.update_controls)
        brush_layout.addWidget(self.brush_scope)
        self.apply_brush_button = QPushButton("Trocar pincel")
        self.apply_brush_button.setToolTip("Escolha um preset no Krita e aplique à curva existente, preservando cor e perfil de espessura")
        self.apply_brush_button.setEnabled(False)
        self.apply_brush_button.clicked.connect(self.apply_current_brush)
        brush_layout.addWidget(self.apply_brush_button)
        self.apply_color_button = QPushButton("Aplicar cor atual")
        self.apply_color_button.setToolTip("Aplica a cor de primeiro plano do Krita ao escopo acima. Nas ferramentas de edição, mudar a cor do Krita também recolore os traços selecionados.")
        self.apply_color_button.setEnabled(False)
        self.apply_color_button.clicked.connect(self.use_foreground)
        brush_layout.addWidget(self.apply_color_button)
        self.brush_progress_row = QWidget()
        progress_layout = QHBoxLayout(self.brush_progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.brush_progress = QProgressBar(); self.brush_progress.setMinimumWidth(80)
        self.cancel_brush_button = QPushButton("Cancelar")
        self.cancel_brush_button.clicked.connect(self.cancel_brush_change)
        progress_layout.addWidget(self.brush_progress, 1); progress_layout.addWidget(self.cancel_brush_button)
        self.brush_progress_row.hide(); brush_layout.addWidget(self.brush_progress_row)
        layout.addWidget(self.brush_group)
        self.selection_label = QLabel()
        self.selection_label.setWordWrap(True); self.selection_label.hide()
        layout.addWidget(self.selection_label)
        self.groups = {}
        forms = {}
        self.field_labels = {}
        for key, title in (("curve", "Suavização"), ("stroke", "Traço"),
                           ("pressure", "Espessura dos pontos"), ("tips", "Pontas")):
            group = QGroupBox(title)
            form = QFormLayout(group)
            form.setContentsMargins(10, 12, 10, 10)
            form.setVerticalSpacing(7)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            self.groups[key], forms[key] = group, form
            layout.addWidget(group)
        self.controls = {}
        for key, label, low, high, value, suffix in (
            ("width", "Espessura base", .1, 2000, 8, " px"),
            ("opacity", "Opacidade", 0, 100, 100, " %"),
            ("minimum", "Mínima", 0, 100, 0, " %"),
            ("taper_start", "Afinar início", 0, 100, 0, " %"),
            ("taper_end", "Afinar fim", 0, 100, 0, " %")):
            control = MixedSpinBox()
            control.setRange(low, high)
            control.setDecimals(1)
            control.setValue(value)
            control.setSuffix(suffix)
            control.setKeyboardTracking(False)
            control.setMinimumWidth(92)
            control.valueChanged.connect(lambda v, name=key: self.property_change(name, v))
            control.sameValueCommitted.connect(lambda v, name=key: self.property_change(name, v))
            self.controls[key] = control
            form = forms["stroke" if key in ("width", "opacity") else "pressure" if key == "minimum" else "tips"]
            form.addRow(label, control)
            self.field_labels[control] = form.labelForField(control)
        self.thickness = MixedSpinBox()
        self.thickness.setRange(0, 2000)
        self.thickness.setDecimals(1)
        self.thickness.setSuffix(" px")
        self.thickness.setToolTip("Diâmetro dos pontos selecionados, antes de Mínima e Afinar pontas; a pressão capturada permanece independente")
        self.thickness.setKeyboardTracking(False)
        self.thickness.valueChanged.connect(self.thickness_change)
        self.thickness.sameValueCommitted.connect(self.thickness_change)
        forms["pressure"].addRow("Espessura", self.thickness)
        self.field_labels[self.thickness] = forms["pressure"].labelForField(self.thickness)
        self.smoothing = SmoothingOptions()
        self.smoothing.changed.connect(self.smoothing_changed)
        forms['curve'].addRow(self.smoothing)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        layout.addStretch()
        self.setMinimumWidth(245)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def set_tool(self, mode):
        self.cancel_color_update()
        self._foreground_color = None
        self.cancel_brush_change()
        labels = ("Linework Brush", "Linework Curve", "Linework Line", "Linework Edit", "Linework Thickness", "Linework Erase")
        modes = ("pen", "curve", "line", "edit", "pressure", "erase")
        self.active = True
        self._error = None
        self.status.hide()
        self.mode = modes[mode]
        if mode == 0: self.smoothing.reload()
        self.selection_label.setVisible(mode in (3, 4))
        self.tool_label.setText(labels[mode])
        self.setWindowTitle(labels[mode])
        self.groups["stroke"].setVisible(mode in (0, 1, 2, 3))
        self.groups["pressure"].setVisible(mode != 5)
        self.groups["tips"].setVisible(mode in (0, 1, 2, 3))
        self.groups["curve"].setVisible(mode == 0)
        self.thickness.setVisible(mode in (3, 4))
        self.field_labels[self.thickness].setVisible(mode in (3, 4))
        self.brush_group.setVisible(mode != 5)
        self.stroke_brush_label.setVisible(mode in (3, 4))
        self.brush_scope.setVisible(mode in (3, 4))
        self.apply_brush_button.setVisible(mode in (3, 4))
        self.apply_color_button.setVisible(mode in (3, 4))
        if self.overlay:
            self.overlay.set_mode(self.mode)
            self.overlay.smoothing_options = list(self.smoothing.values)
            self.overlay.show()
        self.poll()

    def smoothing_changed(self):
        if self.overlay:
            self.overlay.finish_draft()
            self.overlay.smoothing_options = list(self.smoothing.values)

    def pause_tool(self):
        self.cancel_color_update()
        self.cancel_brush_change()
        self.active = False
        overlay = self.overlay
        if overlay:
            overlay.finish_draft()
            if not sip.isdeleted(overlay):
                overlay.hide()
        QTimer.singleShot(0, self.release_native_tool)

    def finish_native_request(self):
        if self.overlay and self.overlay.smoother and self.overlay.draft and not self._writing and not self.overlay._finishing:
            self.overlay.finish_draft()
        if self.overlay and self.overlay._edit_original and not self.overlay._edit_committing:
            self.overlay.restore_edit_preview(cancel=True)
            self.update_controls()

    def release_native_tool(self):
        from .tools import active_tool
        if active_tool() < 0:
            self.clear_binding()

    def current_view(self):
        for window in Krita.instance().windows():
            if window.qwindow() == self._window:
                return window.activeView()
        return None

    def clear_binding(self):
        if self._clearing:
            return
        self._clearing = True
        self._pending_input.clear()
        if not sip.isdeleted(self.input_timer): self.input_timer.stop()
        self.cancel_color_update()
        self._foreground_color = None
        self.cancel_brush_change()
        overlay = self.overlay
        self.overlay = self.native_widget = self.document = self.layer = self.binding = None
        try:
            if overlay:
                overlay.stop_smoothing()
                overlay.restore_edit_preview(cancel=True)
                overlay.renderer.close()
                if not sip.isdeleted(overlay):
                    overlay.preview_timer.stop()
                    overlay.hide()
                    overlay.deleteLater()
        finally:
            self._clearing = False

    def dispose(self):
        self.active = False
        self.clear_binding()
        if not sip.isdeleted(self):
            self.timer.stop()
            QApplication.instance().removeEventFilter(self)

    def new_layer(self):
        view = self.current_view()
        if not view:
            self.status.setText("Abra ou crie uma imagem primeiro.")
            return
        if self.overlay:
            self.overlay.finish_draft()
        try:
            self._writing = True
            document = view.document()
            if document is None:
                return
            preset = view.currentBrushPreset()
            self.brush_label.setText("Pincel: "+(preset.name() if preset else "nenhum"))
            layer = self.create_native_layer(document)
            layer = write_layer(document, layer, [])
            self.clear_binding()
            self.document, self.layer = document, layer
            self._selection_pending = True
            self._selection_deadline = time.monotonic()+3
            QTimer.singleShot(0, self.select_native_layer)
            self.active = True
        except Exception as exc:
            self.fail(exc)
        finally:
            self._writing = False
        self.poll()

    def create_native_layer(self, document):
        # Use Krita's layer action so its layer model, node manager and selection
        # are updated together, including the native Layers docker.
        action = Krita.instance().action("add_new_shape_layer")
        if action is None or not action.isEnabled():
            raise RuntimeError("O Krita não permite criar uma camada vetorial neste documento.")
        before = {layer_id(n) for n in document.rootNode().findChildNodes("", True, False, "vectorlayer")}
        action.trigger()
        document.waitForDone()
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        created = [n for n in document.rootNode().findChildNodes("", True, False, "vectorlayer")
                   if layer_id(n) not in before]
        if len(created) != 1:
            raise RuntimeError("O Krita não criou uma camada vetorial no painel Camadas.")
        layer = created[0]
        layer.setName("Linework — traços editáveis")
        document.setActiveNode(layer)
        return layer

    def poll(self):
        if self._writing or self._clearing or self._brush_change or not self.active or native_busy():
            return
        try:
            view = self.current_view()
            if not view or view.document() is None or not self._canvas.isVisible():
                self.clear_binding()
                return
            document = view.document()
            preset = view.currentBrushPreset()
            self.brush_label.setText("Atual no Krita: "+(preset.name() if preset else "nenhum"))
            active = self.layer if self._selection_pending and self.layer else document.activeNode()
            # Empty documents and transient node-manager updates can report no
            # active node. Keep the explicitly created layer while it exists.
            if active is None and self.layer and self.binding and document.rootNode().uniqueId().toString() == self.binding[0]:
                active = document.nodeByUniqueID(self.layer.uniqueId())
            native = self._canvas
            key = (document.rootNode().uniqueId().toString(), layer_id(active) if active else "", id(native))
            if key != self.binding:
                if self.overlay and self.overlay.draft:
                    self.overlay.finish_draft()
                self.clear_binding()
                if not hasattr(view, "flakeToImageTransform"):
                    raise ValueError("Esta versão do Krita não expõe a transformação do canvas.")
                if view.canvas().wrapAroundMode():
                    raise ValueError("Desative o modo de repetição do canvas para usar Linework.")
                strokes = read_layer(document, active, view)
                self.document = document
                self.layer = active if strokes is not None else None
                self.native_widget = native
                self.binding = key
                self.overlay = NativeCanvasOverlay(view, native, strokes or [], self.layer)
                self.overlay.defaults.update(self._defaults)
                self.overlay.smoothing_options = list(self.smoothing.values)
                self.overlay.mode = self.mode
                self.overlay.changed.connect(self.save_changes)
                self.overlay.selectedChanged.connect(self.update_controls)
                self.overlay.message.connect(self.show_error)
                if self.mode in ('edit', 'pressure') and self.layer:
                    ids = {s.name()[3:] for s in self.layer.shapes() if s.name().startswith('lw_') and s.isSelected()}
                    if ids: self.overlay.select_strokes(ids)
                # Input managers are created with each Krita view. Install last
                # so this opt-in handler sees input before native painting tools.
                QApplication.instance().removeEventFilter(self)
                QApplication.instance().installEventFilter(self)
                self.update_controls()
                self.status.setText(self._error or "Desenhe na tela · os traços são gravados automaticamente na camada.")
                self.status.setVisible(bool(self._error))
            else:
                self.overlay.setGeometry(native.rect())
                self.overlay.sync_transform()
            color = view.foregroundColor().colorForCanvas(view.canvas()).name()
            previous_color, self._foreground_color = self._foreground_color, color
            self._defaults["color"] = self.overlay.defaults["color"] = color
            if previous_color != color:
                # A binding/tool change establishes a baseline; selecting an
                # existing curve must never silently overwrite its saved color.
                ids = self.overlay.selection.ids()
                if previous_color is not None and self.mode in ("edit", "pressure") and self.layer and ids:
                    self._pending_color = (self.binding, frozenset(ids))
                    self.color_timer.start(300)
                self.update_controls()
            if self.mode in ("pen", "curve", "line"):
                self.overlay.defaults.update(width=view.brushSize(), opacity=view.paintingOpacity())
                self.update_controls()
        except Exception as exc:
            self.fail(exc)

    def fail(self, exc):
        self._error = str(exc)
        self.clear_binding()
        self.show_error(self._error)

    def show_error(self, text):
        self.status.setText(text)
        self.status.show()

    def save_changes(self):
        if self._writing or not self.overlay:
            return
        self._writing = True
        try:
            created = self.layer is None
            if self.layer is None:
                self.layer = self.create_native_layer(self.document)
            self.layer = write_layer(self.document, self.layer, self.overlay.strokes, self.overlay.renderer, trusted=True)
            self.overlay.source_layer = self.layer
            if created:
                self._selection_pending = True
                self._selection_deadline = time.monotonic()+3
                QTimer.singleShot(0, self.select_native_layer)
            self.binding = (self.document.rootNode().uniqueId().toString(), layer_id(self.layer), id(self.native_widget))
            self._error = None
            self.status.setText("{} traços editáveis · salve o documento em .kra".format(len(self.overlay.strokes)))
            self.status.hide()
        except Exception as exc:
            self.fail(exc)
        finally:
            self._writing = False

    def select_native_layer(self):
        if self.document and self.layer:
            self.document.setActiveNode(self.layer)
            active = self.document.activeNode()
            if active and active.uniqueId() == self.layer.uniqueId():
                self._selection_pending = False
            elif time.monotonic() < self._selection_deadline:
                QTimer.singleShot(80, self.select_native_layer)
            else:
                self._selection_pending = False

    def update_controls(self):
        self._updating = True
        stroke = self.selected_stroke()
        selected = self.overlay.selected_strokes() if self.overlay and self.mode in ('edit', 'pressure') else []
        point_refs = self.overlay.selected_point_refs() if selected else []
        values = stroke.__dict__ if stroke else self.overlay.defaults if self.overlay else self._defaults
        changing = self._brush_change is not None
        targets = bool(self.overlay and self.overlay.strokes) if self.brush_scope.currentIndex() else stroke is not None
        self.apply_brush_button.setEnabled(bool(targets and self.layer and not self.layer.locked() and not changing))
        self.apply_color_button.setEnabled(self.apply_brush_button.isEnabled())
        if self._foreground_color:
            swatch = QPixmap(16, 16); swatch.fill(QColor(self._foreground_color))
            self.apply_color_button.setIcon(QIcon(swatch))
        self.brush_scope.setEnabled(not changing)
        self.stroke_brush_label.setText("Do traço: "+(stroke.brush['name'] if stroke and stroke.brush else
                                                     "Linha lisa" if stroke else "selecione um traço"))
        names = {s.brush['name'] if s.brush else 'Linha lisa' for s in selected}
        if len(names) > 1: self.stroke_brush_label.setText('Na seleção: vários pincéis')
        self.selection_label.setText('{} {} · {} {}'.format(len(selected), 'traço' if len(selected)==1 else 'traços',
                                                          len(point_refs), 'ponto' if len(point_refs)==1 else 'pontos'))
        for group in self.groups.values():
            group.setEnabled(not changing and (self.mode not in ("edit", "pressure") or stroke is not None))
        for key, control in self.controls.items():
            control.setValue(values[key] if key == "width" else values[key]*100)
            control.set_mixed(len({getattr(s, key) for s in selected}) > 1)
        widths = [point_thickness(s, i) for s, i in point_refs]
        self.thickness.setEnabled(bool(point_refs))
        self.thickness.setValue(widths[0] if widths else 0)
        self.thickness.set_mixed(len({round(width, 6) for width in widths}) > 1)
        self._updating = False

    def selected_stroke(self):
        return self.overlay.active_stroke() if self.overlay and self.mode in ("edit", "pressure") else None

    def apply_current_brush(self):
        if self._brush_change or not self.overlay or not self.layer:
            return
        ids = self.overlay.selection.ids()
        indices = list(range(len(self.overlay.strokes))) if self.brush_scope.currentIndex() else (
            [i for i, s in enumerate(self.overlay.strokes) if s.uid in ids] if self.selected_stroke() else [])
        if not indices:
            return
        try:
            if self.layer.locked():
                raise ValueError("Desbloqueie a camada para trocar o pincel.")
            self.overlay.finish_draft()
            view = self.current_view()
            brush = capture_brush(view)
            updated = copy.deepcopy(self.overlay.strokes)
            changed = []
            for index in indices:
                if updated[index].brush != brush:
                    updated[index].brush = copy.deepcopy(brush)
                    changed.append(updated[index])
            if not changed:
                self.status.setText("Os traços já usam este pincel e suas configurações."); self.status.show()
                return
            # Prepare native appearances incrementally. No stored curve or SVG
            # changes until every target has rendered successfully; one commit
            # produces one undo action even for the complete layer.
            self.start_model_update(updated, changed)
        except Exception as exc:
            self.show_error(str(exc))

    def start_model_update(self, updated, changed, message=None):
        if not changed: return
        view = self.current_view()
        self._brush_change = dict(view=view, document=self.document, layer=self.layer,
            overlay=self.overlay, updated=updated, changed=changed, index=0, images={}, message=message,
            renderer=NativeBrushRenderer(view), baseline=[s.data() for s in self.overlay.strokes])
        self.brush_progress.setRange(0, len(changed)); self.brush_progress.setValue(0)
        self.brush_progress_row.show(); self.status.hide(); self.update_controls(); self.brush_timer.start(0)

    def paint_brush_change(self):
        state = self._brush_change
        if state is None:
            return
        try:
            view = self.current_view()
            active = state['document'].activeNode()
            if (not self.active or self.overlay is not state['overlay'] or not view or
                    view.document() != state['document'] or not active or active.uniqueId() != state['layer'].uniqueId()):
                self.cancel_brush_change(); return
            if state['layer'].locked():
                raise ValueError("A camada foi bloqueada; a troca foi cancelada.")
            if state['index'] < len(state['changed']):
                stroke = state['changed'][state['index']]
                if stroke.brush: state['images'][stroke.uid] = state['renderer'].svg_image(stroke)
                state['index'] += 1; self.brush_progress.setValue(state['index'])
                self.brush_timer.start(0); return
            if [s.data() for s in state['overlay'].strokes] != state['baseline']:
                raise ValueError("Os traços mudaram; aplique o pincel novamente.")
            class Prepared:
                def svg_image(self, stroke): return state['images'][stroke.uid]
            self._writing = True
            try:
                write_layer(state['document'], state['layer'], state['updated'], Prepared())
                overlay = state['overlay']; overlay.strokes = state['updated']
                overlay.history.commit(overlay.strokes)
                overlay.saved_appearances.clear(); overlay.native_preview = None
                overlay.selectedChanged.emit(); overlay.update()
            finally:
                self._writing = False
            count = len(state['changed'])
            message = state['message']
            if message is None:
                name = state['changed'][0].brush['name']
                message = "Pincel “{}” aplicado a {} {}.".format(name, count, 'traço' if count == 1 else 'traços')
            self.finish_brush_change(message)
        except Exception as exc:
            self.finish_brush_change(str(exc))

    def finish_brush_change(self, message=None):
        state, self._brush_change = self._brush_change, None
        self.brush_timer.stop()
        if state:
            state['renderer'].close()
        self.brush_progress_row.hide()
        self.update_controls()
        if message:
            self.status.setText(message); self.status.show()

    def cancel_brush_change(self):
        if self._brush_change:
            self.finish_brush_change("Operação cancelada; os traços foram preservados.")

    def property_change(self, key, value):
        if self._updating or self._brush_change:
            return
        value = value if key == "width" else value/100
        self._defaults[key] = value
        view = self.current_view()
        if view and key == "width":
            view.setBrushSize(value)
        elif view and key == "opacity":
            view.setPaintingOpacity(value)
        if self.overlay:
            self.overlay.defaults[key] = value
            selected = self.overlay.selected_strokes() if self.selected_stroke() else []
            if len(selected) > 1:
                ids = {s.uid for s in selected}; updated = copy.deepcopy(self.overlay.strokes)
                changed = []
                for stroke in updated:
                    if stroke.uid in ids and getattr(stroke, key) != value:
                        setattr(stroke, key, value); changed.append(stroke)
                self.start_model_update(updated, changed, 'Ajuste aplicado a {} traços.'.format(len(changed)))
            elif selected:
                setattr(selected[0], key, value); self.overlay.commit()
            if self.overlay and self.overlay.draft:
                setattr(self.overlay.draft, key, value)
                self.overlay.update()

    def thickness_change(self, value):
        if self._updating or self._brush_change or not self.overlay:
            return
        refs = self.overlay.selected_point_refs() if self.selected_stroke() else []
        if refs:
            keys = {(s.uid, i) for s, i in refs}; updated = copy.deepcopy(self.overlay.strokes); changed = []
            try:
                for stroke in updated:
                    indices = [i for i in range(len(stroke.points)) if (stroke.uid, i) in keys]
                    if not indices or all(math.isclose(point_thickness(stroke, i), value, abs_tol=1e-8) for i in indices): continue
                    ensure_thickness(stroke)
                    for i in indices: set_point_thickness(stroke, i, value)
                    changed.append(stroke)
                self.start_model_update(updated, changed, 'Espessura aplicada a {} pontos.'.format(len(refs)))
            except Exception as exc:
                self.show_error(str(exc)); self.update_controls()

    def cancel_color_update(self):
        # Canvas destruction can dispose a controller after Qt has already
        # deleted its child timers. Keep shutdown safe in that order as well.
        if not sip.isdeleted(self.color_timer):
            self.color_timer.stop()
        self._pending_color = None

    def apply_pending_color(self):
        pending = self._pending_color
        if not pending:
            return
        binding, ids = pending
        if not self.active or self.binding != binding or self.mode not in ("edit", "pressure") or not self.overlay:
            self.cancel_color_update(); return
        # Wait until the picker/drag and native rendering finish. Reading the
        # final foreground avoids repainting for every intermediate slider value.
        if (self._writing or self._brush_change or native_busy() or self.overlay.drag or
                self.overlay._edit_original or QApplication.activeModalWidget() or
                QApplication.mouseButtons() != Qt.NoButton):
            self.color_timer.start(150); return
        self.cancel_color_update()
        view = self.current_view()
        if view and view.document() == self.document:
            color = view.foregroundColor().colorForCanvas(view.canvas()).name()
            self.apply_color(color, ids)

    def use_foreground(self):
        self.cancel_color_update()
        view = self.current_view()
        if view:
            color = view.foregroundColor().colorForCanvas(view.canvas()).name()
            self.apply_color(color)

    def apply_color(self, color, ids=None):
        if self._updating or self._writing or self._brush_change or not self.active:
            return
        self._defaults["color"] = color
        if not self.overlay:
            return
        self.overlay.defaults["color"] = color
        if not self.layer or self.mode not in ("edit", "pressure"):
            return
        try:
            if self.layer.locked():
                raise ValueError("Desbloqueie a camada para trocar a cor.")
            if self.overlay.drag or self.overlay._edit_original:
                return
            if ids is None:
                ids = ({s.uid for s in self.overlay.strokes} if self.brush_scope.currentIndex()
                       else self.overlay.selection.ids())
            updated = copy.deepcopy(self.overlay.strokes)
            changed = []
            for stroke in updated:
                if stroke.uid in ids and stroke.color != color:
                    stroke.color = color; changed.append(stroke)
            self.start_model_update(updated, changed, "Cor {} aplicada a {} {}.".format(
                color, len(changed), "traço" if len(changed) == 1 else "traços"))
        except Exception as exc:
            self.show_error(str(exc))

    def export_svg(self):
        if not self.overlay:
            self.status.setText("Selecione uma ferramenta Linework e uma camada para exportar.")
            return
        self.overlay.finish_draft()
        path, _ = QFileDialog.getSaveFileName(self, "Exportar vetores", "linework.svg", "SVG (*.svg)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(svg(self.overlay.strokes, self.document.width(), self.document.height(), 96, 96,
                                     self.overlay.renderer))
            except OSError as exc:
                self.status.setText(str(exc))

    def input_busy(self):
        return (self._input_depth or self._writing or self._clearing or
                (self.overlay and (self.overlay._finishing or self.overlay.renderer.busy)) or native_busy())

    def copy_input(self, event):
        kind = event.type()
        if kind in (QEvent.TabletPress, QEvent.TabletMove, QEvent.TabletRelease):
            copied = QTabletEvent(kind, event.posF(), event.globalPosF(), event.device(),
                event.pointerType(), event.pressure(), event.xTilt(), event.yTilt(),
                event.tangentialPressure(), event.rotation(), event.z(), event.modifiers(),
                event.uniqueId(), event.button(), event.buttons())
        elif kind in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
            copied = QKeyEvent(kind, event.key(), event.modifiers(), event.nativeScanCode(),
                event.nativeVirtualKey(), event.nativeModifiers(), event.text(),
                event.isAutoRepeat(), event.count())
        else:
            copied = QMouseEvent(kind, event.localPos(), event.windowPos(), event.screenPos(),
                event.button(), event.buttons(), event.modifiers(), event.source())
        copied.setTimestamp(event.timestamp())
        return copied

    def drain_input(self):
        if not self.active or not self.overlay:
            self._pending_input.clear(); return
        if self.input_busy():
            self.input_timer.start(10); return
        # Replaying through Qt preserves the native handling of navigation and
        # shortcuts. The captured events own their data after the originals die.
        while self._pending_input and self.active and self.overlay:
            overlay, mode, event = self._pending_input.popleft()
            if overlay is not self.overlay or mode != self.mode:
                continue
            self._replaying_input = True
            try:
                QApplication.sendEvent(self.native_widget, event)
            finally:
                self._replaying_input = False
            if self.input_busy():
                self.input_timer.start(10); break

    def eventFilter(self, watched, event):
        input_event = event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick, QEvent.MouseMove, QEvent.TabletPress, QEvent.TabletMove,
            QEvent.TabletRelease, QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride)
        if (watched == self.native_widget and self.overlay and self.active and input_event
                and not self._brush_change):
            if not self._replaying_input:
                if event.type() in (QEvent.TabletPress, QEvent.TabletMove, QEvent.TabletRelease):
                    self._tablet_until = time.monotonic()+.15
                elif event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                                     QEvent.MouseButtonDblClick, QEvent.MouseMove):
                    if time.monotonic() < self._tablet_until:
                        event.accept(); return True
            # Krita's native waits run a nested Qt loop. Never let input mutate
            # the stroke list or scratch image in the middle of another event
            # or a commit; retain gestures in order instead of dropping them.
            if self.input_busy() or (self._pending_input and not self._replaying_input):
                self._pending_input.append((self.overlay, self.mode, self.copy_input(event)))
                self.input_timer.start(10)
                event.accept(); return True
            self._input_depth += 1
            try:
                return self.canvas_event(watched, event)
            finally:
                self._input_depth -= 1
                if self._pending_input and not self._input_depth:
                    self.input_timer.start(0)
        return self.canvas_event(watched, event)

    def canvas_event(self, watched, event):
        # Restore while the view/document are still alive, before Qt starts
        # destroying a window or hiding a closing/switched canvas.
        if self.overlay and self.overlay._edit_original and (
                (watched == self._window and event.type() == QEvent.Close) or
                (watched == self._canvas and event.type() in (QEvent.Close, QEvent.Hide))):
            self.overlay.restore_edit_preview(cancel=True)
            if event.type() == QEvent.Close:
                # Let the canvas consume the restored projection while its
                # OpenGL context still exists, before the native close handler.
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        if watched != self.native_widget or not self.overlay or not self.active:
            return False
        etype = event.type()
        if self._brush_change:
            if etype == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.cancel_brush_change(); return True
            if etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove,
                         QEvent.TabletPress, QEvent.TabletRelease, QEvent.TabletMove,
                         QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
                return True
        if etype == QEvent.Paint or etype == QEvent.Resize:
            self.overlay.update()
            return False
        if etype == QEvent.Leave:
            self.overlay.hover_pos = None; self.overlay.update()
            return False
        if etype in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
            key = event.key()
            if key == Qt.Key_Space:
                if etype != QEvent.ShortcutOverride:
                    self._space = etype == QEvent.KeyPress
                return False
            undo = key == Qt.Key_Z and event.modifiers() & Qt.ControlModifier
            redo = key == Qt.Key_Y and event.modifiers() & Qt.ControlModifier
            select_all = key == Qt.Key_A and event.modifiers() & Qt.ControlModifier and self.mode in ('edit', 'pressure')
            if undo or redo or select_all or key in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
                if etype == QEvent.ShortcutOverride:
                    event.accept()
                    return True
                if etype == QEvent.KeyPress:
                    if undo:
                        self.overlay.redo() if event.modifiers() & Qt.ShiftModifier else self.overlay.undo()
                    elif redo:
                        self.overlay.redo()
                    elif select_all: self.overlay.select_all()
                    else:
                        self.overlay.keyPressEvent(event)
                event.accept()
                return True
            return False
        tablet = etype in (QEvent.TabletPress, QEvent.TabletMove, QEvent.TabletRelease)
        mouse = etype in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease,
                         QEvent.MouseButtonDblClick)
        if not tablet and not mouse:
            return False
        double_click = etype == QEvent.MouseButtonDblClick
        press = etype in (QEvent.TabletPress, QEvent.MouseButtonPress) or double_click
        release = etype in (QEvent.TabletRelease, QEvent.MouseButtonRelease)
        if press:
            self._passing_navigation = (self._space or event.button() == Qt.MiddleButton or
                bool(event.modifiers() & Qt.ControlModifier) or
                (bool(event.modifiers() & Qt.ShiftModifier) and self.mode not in ('edit', 'pressure')) or
                (event.button() == Qt.RightButton and self.mode not in ("curve", "line")))
        if self._passing_navigation or self._space:
            if release:
                self._passing_navigation = False
            return False
        if not press and not release and event.buttons() == Qt.NoButton and self.overlay.drag is None:
            self.overlay.hover_pos = event.posF() if tablet else event.localPos()
            self.overlay.update()
            return False
        try:
            if press:
                self.poll()
                if not self.overlay:
                    return False
            pos = event.posF() if tablet else event.localPos()
            pressure = event.pressure() if tablet else 1
            if double_click and self.mode == "edit" and event.button() == Qt.LeftButton:
                self.overlay.insert_at(pos)
            elif press:
                self.overlay.begin(pos, pressure, event.button() if event.button() != Qt.NoButton else Qt.LeftButton, event.modifiers())
            elif release:
                self.overlay.end(pos, pressure)
            else:
                self.overlay.move(pos, pressure, event.modifiers())
            event.accept()
            return True
        except Exception as exc:
            self.fail(exc)
            return True
