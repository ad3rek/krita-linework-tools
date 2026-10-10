# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import math
import time
from .qt import event_position, Qt, QPointF, QRectF, QEvent, pyqtSignal
from .qt import QColor, QPainter, QPainterPath, QPen, QImage
from .qt import QWidget
from .qt import QKeySequence
from .selection import Selection
from .spatial import SpatialIndex
from .model import (Point, Stroke, History, clamp, distance, segment_distance,
                    samples, outline, simplify, svg, geometry_key, handle_vector,
                    closest_location, insert_point)
from .model import set_point_thickness
from .native_brush import point_thickness, ensure_thickness


def painter_path(stroke):
    poly = outline(stroke)
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
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
        self._spatial = None
        self._spatial_strokes = None
        self._spatial_dirty = set()
        self._spatial_sync = False
        self.changed.connect(self.invalidate_spatial)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking, True)

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

    def invalidate_spatial(self, ids=None):
        self._spatial_dirty.update(self.selection.ids() if ids is None else ids)
        self._spatial_sync = True

    def spatial_index(self):
        if self._spatial is None or self._spatial_strokes is not self.strokes:
            self._spatial = SpatialIndex(self.strokes)
            self._spatial_strokes = self.strokes
        elif self._spatial_sync:
            current = {s.uid:s for s in self.strokes}
            for uid in self._spatial.strokes.keys()-current.keys(): self._spatial.remove(uid)
            for uid in self._spatial_dirty | (current.keys()-self._spatial.strokes.keys()):
                if uid in current: self._spatial.update(current[uid])
            self._spatial.order = {s.uid:i for i,s in enumerate(self.strokes)}
        self._spatial_dirty.clear(); self._spatial_sync = False
        return self._spatial

    def hit_at(self, p):
        threshold = self.pick_radius/self.zoom
        # Pick the nearest anchor; selection priority only breaks equal distances.
        ids = self.selection.ids()
        spatial = self.spatial_index()
        box = p.x-threshold, p.y-threshold, p.x+threshold, p.y+threshold
        if self.selection_mode != 'stroke':
            best_point = None; best_distance = threshold
            candidates = sorted(spatial.anchors_in(box), key=lambda key:
                (0 if key[0] in ids else 1, spatial.order[key[0]] if key[0] in ids else -spatial.order[key[0]], key[1]))
            for uid, closest in candidates:
                stroke = spatial.strokes[uid]; d = distance(p, stroke.points[closest])
                if d <= threshold and (best_point is None or d < best_distance-1e-9):
                    best_point, best_distance = (stroke, closest), d
            if best_point is not None: return best_point
            if self.selection_mode == 'point': return None, -1
        best = threshold
        hit = None
        for uid in sorted(spatial.strokes_in(box), key=spatial.order.get, reverse=True):
            stroke = spatial.strokes[uid]
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
            spatial = self.spatial_index()
            if any(distance(p, spatial.strokes[uid].points[i]) < best
                   for uid,i in spatial.anchors_in((p.x-best,p.y-best,p.x+best,p.y+best))):
                return None
        return side_hit

    def thickness_guide(self, stroke, index):
        """The visible diameter guide, in document coordinates."""
        tangent = handle_vector(stroke, index, 'out') or handle_vector(stroke, index, 'in')
        if tangent is None or math.hypot(*tangent) < 1e-7:
            a, b = stroke.points[max(0, index-1)], stroke.points[min(len(stroke.points)-1, index+1)]
            tangent = b.x-a.x, b.y-a.y
        length = math.hypot(*tangent)
        normal = (-tangent[1]/length, tangent[0]/length) if length else (0, 1)
        radius = (stroke.width*stroke.minimum+(1-stroke.minimum)*point_thickness(stroke, index))/2
        return normal, max(6/self.zoom, min(radius, 100/self.zoom))

    def thickness_handle_at(self, p):
        if self.mode != 'pressure':
            return None
        best = self.pick_radius/self.zoom
        hit = None
        for stroke in self.selected_strokes():
            for index, anchor in enumerate(stroke.points):
                if self.locked_point is not None and (stroke.uid, index) != self.locked_point:
                    continue
                normal, radius = self.thickness_guide(stroke, index)
                for sign in (-1, 1):
                    end = Point(anchor.x+sign*normal[0]*radius, anchor.y+sign*normal[1]*radius)
                    d = distance(p, end)
                    # Short guides must still allow clicking their anchor.
                    if d <= best and d < distance(p, anchor):
                        best, hit = d, (stroke, index, tuple(sign*v for v in normal))
        if hit is not None:
            spatial = self.spatial_index()
            if any(distance(p, spatial.strokes[uid].points[i]) < best
                   for uid, i in spatial.anchors_in((p.x-best, p.y-best, p.x+best, p.y+best))):
                return None
        return hit

    def begin_thickness_drag(self, pos, direction=None):
        self.drag = 'pressure'
        self.drag_start = pos
        self._pressure_start = self.local_point(pos)
        self._pressure_direction = direction
        self._initial_thicknesses = {(s.uid, i): point_thickness(s, i)
                                    for s, i in self.selected_point_refs()}

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

    def begin(self, pos, pressure, button=Qt.MouseButton.LeftButton, modifiers=Qt.KeyboardModifier.NoModifier):
        self.setFocus()
        self.hover_pos = pos
        if button == Qt.MouseButton.MiddleButton or (modifiers & Qt.KeyboardModifier.ShiftModifier and self.mode not in ("edit", "pressure")):
            self.drag = "pan"
            self.last_pos = pos
            return
        if button == Qt.MouseButton.RightButton:
            self.finish_draft()
            return
        if button != Qt.MouseButton.LeftButton:
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
            diameter = self.thickness_handle_at(p) if not modifiers & Qt.KeyboardModifier.ShiftModifier else None
            if diameter:
                stroke, index, direction = diameter
                if (stroke.uid, index) not in self.selection.point_keys(self.strokes):
                    self.selection.set_points([(stroke.uid, index)])
                self.selection.primary = stroke.uid, index
                self.begin_thickness_drag(pos, direction)
                self.selectedChanged.emit(); self.update()
                return
            side = self.handle_at(p) if not modifiers & Qt.KeyboardModifier.ShiftModifier else None
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
                    self.begin_thickness_drag(pos)
                else:
                    self.drag = 'point'; self.last_doc = p
                self.update(); return
            if self.mode == "edit" and modifiers & Qt.KeyboardModifier.AltModifier:
                self.insert_at(pos)
                return
            before = copy.deepcopy(self.selection)
            hit, index = self.select_at(p, bool(modifiers & Qt.KeyboardModifier.ShiftModifier))
            if modifiers & Qt.KeyboardModifier.ShiftModifier and hit:
                self.update(); return
            if not hit and self.mode in ("edit", "pressure"):
                self.drag = "select"; self._selection_before = before
                self._selection_add = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
                self._selection_start = p; self._selection_end = p
                self.update(); return
            active = self.active_stroke()
            if active:
                if self.mode == "erase":
                    self.delete_stroke()
                elif self.mode == "pressure":
                    if self.point_index < 0:
                        self.selection.primary = active.uid, min(range(len(active.points)), key=lambda i: distance(p, active.points[i]))
                    self.begin_thickness_drag(pos)
                else:
                    self.drag = "point" if self.point_index >= 0 else "stroke"
                    self.last_doc = p
        self.update()
        self.selectedChanged.emit()

    def move(self, pos, pressure, modifiers=Qt.KeyboardModifier.NoModifier):
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
            spatial = self.spatial_index()
            keys = {(uid,i) for uid,i in spatial.anchors_in((box.left(),box.top(),box.right(),box.bottom()))
                    if box.contains(QPointF(spatial.strokes[uid].points[i].x,spatial.strokes[uid].points[i].y))}
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
                    if self._opposite_length is not None and length > 1e-7 and not modifiers & Qt.KeyboardModifier.AltModifier:
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
                    if self._pressure_direction is not None:
                        dx, dy = p.x-self._pressure_start.x, p.y-self._pressure_start.y
                        nx, ny = self._pressure_direction
                        delta = 2*(dx*nx+dy*ny)/max(.01, 1-stroke.minimum)
                    for target in self.selected_strokes(): ensure_thickness(target)
                    for target, index in self.selected_point_refs():
                        set_point_thickness(target, index, self._initial_thicknesses[(target.uid, index)]+delta)
                    self.selectedChanged.emit()
            self.invalidate_spatial()
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
        if event.type() in (QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease):
            self._tablet_until = time.monotonic()+.15
            if event.type() == QEvent.Type.TabletPress:
                button = event.button() if event.button() != Qt.MouseButton.NoButton else Qt.MouseButton.LeftButton
                self.begin(event_position(event), event.pressure(), button, event.modifiers())
            elif event.type() == QEvent.Type.TabletMove:
                self.move(event_position(event), event.pressure(), event.modifiers())
            else:
                self.end(event_position(event), event.pressure())
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.insert_at(QPointF(event.pos()))

    def mouseReleaseEvent(self, event):
        if time.monotonic() >= self._tablet_until:
            self.end(QPointF(event.pos()), 1)

    def wheelEvent(self, event):
        pos = event_position(event)
        doc = (pos-self.offset)/self.zoom
        self.zoom = clamp(self.zoom*1.2**(event.angleDelta().y()/120), .005, 100)
        self.offset = pos-doc*self.zoom
        self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_draft()
        elif event.key() == Qt.Key.Key_Escape:
            if self.drag == "select": self.selection = self._selection_before
            elif self.drag is None: self.selection.clear()
            self.draft = None
            self.drag = None
            self.selectedChanged.emit()
            self.update()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.mode == "edit" and self.selection.points:
                self.invalidate_spatial(self.selection.ids())
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
