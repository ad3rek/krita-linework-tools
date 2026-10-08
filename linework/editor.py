# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import math
import time
from PyQt5.QtCore import Qt, QPointF, QRectF, QEvent, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QImage
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QKeySequence
from .selection import Selection
from .model import (Point, Stroke, History, clamp, distance, segment_distance,
                    samples, outline, simplify, svg, geometry_key, handle_vector,
                    closest_location, insert_point)
from .model import set_point_thickness
from .native_brush import point_thickness, ensure_thickness


def painter_path(stroke):
    poly = outline(stroke)
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    if poly:
        path.moveTo(*poly[0])
        for x, y in poly[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
    return path


class LineworkCanvas(QWidget):
    changed = pyqtSignal()
    selectedChanged = pyqtSignal()
    message = pyqtSignal(str)

    def __init__(self, width, height, strokes, parent=None):
        super().__init__(parent)
        self.doc_width, self.doc_height = width, height
        self.strokes = copy.deepcopy(strokes)
        self.history = History(self.strokes)
        self.mode = "pen"
        self.selection = Selection()
        self.selection_mode = 'auto'
        self.pick_radius = 16.0  # Logical screen pixels, independent of canvas zoom.
        self.locked_point = None
        self.handle_side = None
        self.zoom = 1.0
        self.offset = QPointF(20, 20)
        self.did_fit = False
        self.background = QImage()
        self.draft = None
        self.defaults = dict(width=8, color="#202020", opacity=1,
                             minimum=0, taper_start=0, taper_end=0)
        self.smoothing = 1.5
        self.drag = None
        self.last_pos = QPointF()
        self.hover_pos = None
        self._tablet_until = 0
        self._paths = {}
        self._centers = {}
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TabletTracking, True)

    def active_stroke(self):
        return self.strokes[self.selected] if 0 <= self.selected < len(self.strokes) else None

    @property
    def selected(self):
        uid = self.selection.primary[0]
        return next((i for i, s in enumerate(self.strokes) if s.uid == uid), -1)

    @selected.setter
    def selected(self, index):
        self.selection.set_strokes([self.strokes[index].uid] if 0 <= index < len(self.strokes) else [])

    @property
    def point_index(self): return self.selection.primary[1]

    @point_index.setter
    def point_index(self, index):
        uid = self.selection.primary[0]
        if uid is not None and index >= 0: self.selection.set_points([(uid, index)])
        else: self.selection.primary = uid, -1

    def selected_strokes(self):
        ids = self.selection.ids()
        return [s for s in self.strokes if s.uid in ids]

    def selected_point_refs(self):
        keys = self.selection.point_keys(self.strokes)
        return [(s, i) for s in self.strokes for i in range(len(s.points)) if (s.uid, i) in keys]

    def select_strokes(self, ids):
        self.selection.set_strokes(ids); self.selection.prune(self.strokes)
        self.selectedChanged.emit(); self.update()

    def select_all(self):
        if self.locked_point is not None: return
        if self.selection_mode == 'stroke':
            self.select_strokes(s.uid for s in self.strokes); return
        self.selection.set_points((s.uid, i) for s in self.strokes for i in range(len(s.points)))
        self.selectedChanged.emit(); self.update()

    def local_point(self, pos, pressure=1):
        return Point((pos.x()-self.offset.x())/self.zoom,
                     (pos.y()-self.offset.y())/self.zoom, pressure)

    def cached_path(self, stroke):
        key = (stroke.width, stroke.minimum, stroke.taper_start, stroke.taper_end,
               geometry_key(stroke))
        cached = self._paths.get(stroke.uid)
        if cached is None or cached[0] != key:
            cached = (key, painter_path(stroke))
            self._paths[stroke.uid] = cached
        return cached[1]

    def cached_center(self, stroke):
        key = geometry_key(stroke)
        cached = self._centers.get(stroke.uid)
        if cached is None or cached[0] != key:
            cached = (key, samples(stroke))
            self._centers[stroke.uid] = cached
        return cached[1]

    def hit_at(self, p):
        threshold = self.pick_radius/self.zoom
        # Pick the nearest anchor; selection priority only breaks equal distances.
        selected = self.selected_strokes()
        ids = self.selection.ids()
        candidates = selected+[s for s in reversed(self.strokes) if s.uid not in ids]
        if self.selection_mode != 'stroke':
            best_point = None; best_distance = threshold
            for stroke in candidates:
                if not stroke.points: continue
                closest = min(range(len(stroke.points)), key=lambda i: distance(p, stroke.points[i]))
                d = distance(p, stroke.points[closest])
                if d <= threshold and (best_point is None or d < best_distance-1e-9):
                    best_point, best_distance = (stroke, closest), d
            if best_point is not None: return best_point
            if self.selection_mode == 'point': return None, -1
        best = threshold
        hit = None
        for index in reversed(range(len(self.strokes))):
            stroke = self.strokes[index]
            center = self.cached_center(stroke)
            if len(center) == 1:
                d = distance(p, center[0])
            else:
                d = min(segment_distance(p, a, b)[0] for a, b in zip(center, center[1:]))
            # Include the visible outline of thick strokes in hit testing.
            if self.cached_path(stroke).contains(QPointF(p.x, p.y)):
                d = 0
            if d < best:
                best, hit = d, stroke
                if d == 0:
                    break
        return hit, -1

    def select_at(self, p, additive=False):
        stroke, index = self.hit_at(p)
        if stroke:
            key = stroke.uid, index
            if additive:
                if index >= 0: self.selection.toggle_point(stroke.uid, index, self.strokes)
                else: self.selection.toggle_stroke(stroke.uid)
            else:
                if index >= 0:
                    selected = key in self.selection.point_keys(self.strokes)
                    if not selected or (not self.selection.points and len(self.selection.strokes) == 1):
                        self.selection.set_points([key])
                elif stroke.uid not in self.selection.strokes:
                    self.selection.set_strokes([stroke.uid])
                self.selection.primary = key
        elif not additive: self.selection.clear()
        self.selectedChanged.emit()
        return stroke, index

    def handle_at(self, p):
        stroke = self.active_stroke()
        if self.mode != "edit" or self.selection_mode == 'stroke' or stroke is None or self.point_index < 0:
            return None
        anchor = stroke.points[self.point_index]
        anchor_distance = distance(p, anchor)
        best = self.pick_radius/self.zoom
        side_hit = None
        for side in ("in", "out"):
            vector = handle_vector(stroke, self.point_index, side)
            if vector:
                d = distance(p, Point(anchor.x+vector[0], anchor.y+vector[1]))
                if d <= best and d < anchor_distance:
                    best, side_hit = d, side
        if side_hit is not None and self.locked_point is None:
            if any(distance(p, point) < best for target in self.strokes for point in target.points):
                return None
        return side_hit

    def insert_at(self, pos):
        if self.mode != "edit" or self.locked_point is not None:
            return
        self.select_at(self.local_point(pos))
        stroke = self.active_stroke()
        if stroke is None or len(stroke.points) < 2:
            return
        _, index, t = closest_location(stroke, self.local_point(pos))
        count = len(stroke.points)
        self.point_index = insert_point(stroke, index, t)
        if len(stroke.points) != count:
            self.commit()
        self.selectedChanged.emit()
        self.update()

    def begin(self, pos, pressure, button=Qt.LeftButton, modifiers=Qt.NoModifier):
        self.setFocus()
        self.hover_pos = pos
        if button == Qt.MiddleButton or (modifiers & Qt.ShiftModifier and self.mode not in ("edit", "pressure")):
            self.drag = "pan"
            self.last_pos = pos
            return
        if button == Qt.RightButton:
            self.finish_draft()
            return
        if button != Qt.LeftButton:
            return
        p = self.local_point(pos, pressure)
        if not (0 <= p.x <= self.doc_width and 0 <= p.y <= self.doc_height):
            return
        if self.mode == "pen":
            self.draft = Stroke([p], **self.defaults)
            self.selected, self.point_index = -1, -1
            self.drag = "pen"
            self.selectedChanged.emit()
        elif self.mode in ("curve", "line"):
            if self.draft is None:
                self.draft = Stroke([], kind=self.mode, **self.defaults)
                self.selected = self.point_index = -1
            self.draft.points.append(p)
        else:
            side = self.handle_at(p) if not modifiers & Qt.ShiftModifier else None
            if side:
                self.handle_side = side
                opposite = handle_vector(self.active_stroke(), self.point_index,
                                         "out" if side == "in" else "in")
                self._opposite_length = math.hypot(*opposite) if opposite is not None else None
                self.drag = "handle"
                return
            if self.locked_point is not None and self.mode in ('edit', 'pressure'):
                stroke = self.active_stroke()
                if stroke is None or self.point_index < 0 or distance(p, stroke.points[self.point_index]) > self.pick_radius/self.zoom:
                    return
                # A miss or Shift-click cannot replace the pinned anchor.
                if self.mode == 'pressure':
                    self.drag = 'pressure'
                    self._initial_thicknesses = {(s.uid, i): point_thickness(s, i) for s, i in self.selected_point_refs()}
                    self.drag_start = pos
                else:
                    self.drag = 'point'; self.last_doc = p
                self.update(); return
            if self.mode == "edit" and modifiers & Qt.AltModifier:
                self.insert_at(pos)
                return
            before = copy.deepcopy(self.selection)
            hit, index = self.select_at(p, bool(modifiers & Qt.ShiftModifier))
            if modifiers & Qt.ShiftModifier and hit:
                self.update(); return
            if not hit and self.mode in ("edit", "pressure"):
                self.drag = "select"; self._selection_before = before
                self._selection_add = bool(modifiers & Qt.ShiftModifier)
                self._selection_start = p; self._selection_end = p
                self.update(); return
            active = self.active_stroke()
            if active:
                if self.mode == "erase":
                    self.delete_stroke()
                elif self.mode == "pressure":
                    if self.point_index < 0:
                        self.selection.primary = active.uid, min(range(len(active.points)), key=lambda i: distance(p, active.points[i]))
                    self.drag = "pressure"
                    self._initial_thicknesses = {(s.uid, i): point_thickness(s, i) for s, i in self.selected_point_refs()}
                    self.drag_start = pos
                else:
                    self.drag = "point" if self.point_index >= 0 else "stroke"
                    self.last_doc = p
        self.update()
        self.selectedChanged.emit()

    def move(self, pos, pressure, modifiers=Qt.NoModifier):
        self.hover_pos = pos
        if self.drag == "pan":
            self.offset += pos-self.last_pos
            self.last_pos = pos
        elif self.drag == "pen" and self.draft:
            p = self.local_point(pos, pressure)
            previous = self.draft.points[-1]
            if len(self.draft.points) < 20000 and (distance(p, previous)*self.zoom >= 1 or abs(p.pressure-previous.pressure) > .03):
                self.draft.points.append(p)
        elif self.drag == "select":
            self._selection_end = self.local_point(pos, pressure)
            box = QRectF(QPointF(self._selection_start.x, self._selection_start.y),
                         QPointF(self._selection_end.x, self._selection_end.y)).normalized()
            keys = {(s.uid, i) for s in self.strokes for i, p in enumerate(s.points) if box.contains(QPointF(p.x, p.y))}
            if self._selection_add: keys.update(self._selection_before.point_keys(self.strokes))
            if self.selection_mode == 'stroke':
                ids = {uid for uid, _ in keys}
                if self._selection_add: ids.update(self._selection_before.ids())
                self.selection.set_strokes(ids)
            else: self.selection.set_points(keys)
            self.selectedChanged.emit()
        elif self.drag in ("point", "stroke", "pressure", "handle"):
            stroke = self.active_stroke()
            if stroke:
                p = self.local_point(pos, pressure)
                if self.drag == "point":
                    dx, dy = p.x-self.last_doc.x, p.y-self.last_doc.y
                    for target, index in self.selected_point_refs():
                        target.points[index].x += dx; target.points[index].y += dy
                    self.last_doc = p
                elif self.drag == "handle":
                    point = stroke.points[self.point_index]
                    vector = p.x-point.x, p.y-point.y
                    setattr(point, "handle_"+self.handle_side, vector)
                    length = math.hypot(*vector)
                    if self._opposite_length is not None and length > 1e-7 and not modifiers & Qt.AltModifier:
                        opposite = "out" if self.handle_side == "in" else "in"
                        setattr(point, "handle_"+opposite,
                                tuple(-v*self._opposite_length/length for v in vector))
                elif self.drag == "stroke":
                    dx, dy = p.x-self.last_doc.x, p.y-self.last_doc.y
                    for target in self.selected_strokes():
                        for point in target.points:
                            point.x += dx; point.y += dy
                    self.last_doc = p
                else:
                    delta = (self.drag_start.y()-pos.y())/self.zoom
                    for target in self.selected_strokes(): ensure_thickness(target)
                    for target, index in self.selected_point_refs():
                        set_point_thickness(target, index, self._initial_thicknesses[(target.uid, index)]+delta)
                    self.selectedChanged.emit()
        self.update()

    def end(self, pos, pressure):
        if self.drag == "pen" and self.draft:
            # A tablet release usually reports zero pressure; retain its last value.
            final = self.local_point(pos, self.draft.points[-1].pressure)
            if distance(final, self.draft.points[-1]) > 1e-7:
                self.draft.points.append(final)
            self.draft.points = simplify(self.draft.points, self.smoothing, self.draft.width/2)
            self.finish_draft()
        elif self.drag in ("point", "stroke", "pressure", "handle"):
            self.commit()
        elif self.drag == "select":
            self.selectedChanged.emit()
        self.drag = None
        self.update()

    def event(self, event):
        if event.type() in (QEvent.TabletPress, QEvent.TabletMove, QEvent.TabletRelease):
            self._tablet_until = time.monotonic()+.15
            if event.type() == QEvent.TabletPress:
                button = event.button() if event.button() != Qt.NoButton else Qt.LeftButton
                self.begin(event.posF(), event.pressure(), button, event.modifiers())
            elif event.type() == QEvent.TabletMove:
                self.move(event.posF(), event.pressure(), event.modifiers())
            else:
                self.end(event.posF(), event.pressure())
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if time.monotonic() >= self._tablet_until:
            self.begin(QPointF(event.pos()), 1, event.button(), event.modifiers())

    def mouseMoveEvent(self, event):
        if time.monotonic() >= self._tablet_until:
            self.move(QPointF(event.pos()), 1, event.modifiers())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.insert_at(QPointF(event.pos()))

    def mouseReleaseEvent(self, event):
        if time.monotonic() >= self._tablet_until:
            self.end(QPointF(event.pos()), 1)

    def wheelEvent(self, event):
        pos = event.posF()
        doc = (pos-self.offset)/self.zoom
        self.zoom = clamp(self.zoom*1.2**(event.angleDelta().y()/120), .005, 100)
        self.offset = pos-doc*self.zoom
        self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_draft()
        elif event.key() == Qt.Key_Escape:
            if self.drag == "select": self.selection = self._selection_before
            elif self.drag is None: self.selection.clear()
            self.draft = None
            self.drag = None
            self.selectedChanged.emit()
            self.update()
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.mode == "edit" and self.selection.points:
                for stroke in self.selected_strokes():
                    indices = {i for uid, i in self.selection.points if uid == stroke.uid}
                    stroke.points = [p for i, p in enumerate(stroke.points) if i not in indices]
                self.strokes = [s for s in self.strokes if s.points and s.uid not in self.selection.strokes]
                self.selection.clear(); self.commit()
            else:
                self.delete_stroke()
        else:
            super().keyPressEvent(event)

    def set_mode(self, mode):
        self.finish_draft()
        self.mode = mode
        self.drag = None
        self.update()
        self.selectedChanged.emit()

    def finish_draft(self):
        if self.draft and self.draft.points:
            self.strokes.append(self.draft)
            self.selected = len(self.strokes)-1
            self.point_index = -1
            self.draft = None
            self.commit()

    def commit(self):
        self.history.commit(self.strokes)
        self.changed.emit()
        self.selectedChanged.emit()
        self.update()

    def delete_stroke(self):
        if self.selection.ids():
            self.strokes = [s for s in self.strokes if s.uid not in self.selection.ids()]
            self.selection.prune(self.strokes)
            self.commit()

    def duplicate(self):
        stroke = self.active_stroke()
        if stroke:
            from uuid import uuid4
            duplicate = copy.deepcopy(stroke)
            duplicate.uid = uuid4().hex
            for p in duplicate.points:
                p.x += 12/self.zoom
                p.y += 12/self.zoom
            self.strokes.append(duplicate)
            self.selected = len(self.strokes)-1
            self.point_index = -1
            self.commit()

    def undo(self):
        if self.draft:
            if self.mode in ("curve", "line") and len(self.draft.points) > 1:
                self.draft.points.pop()
            else:
                self.draft = None
        else:
            self.strokes = self.history.undo()
            self.selection.prune(self.strokes)
            self.changed.emit()
        self.selectedChanged.emit()
        self.update()

    def redo(self):
        self.strokes = self.history.redo()
        self.selection.prune(self.strokes)
        self.changed.emit()
        self.selectedChanged.emit()
        self.update()
