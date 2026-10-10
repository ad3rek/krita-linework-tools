"""Independent editable centerlines and variable-width SVG outlines.

No SAI executable, code, file format or binary assets are used at runtime.
Coordinates and widths are in document pixels.
"""
# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from html import escape

MAX_POINTS = 20000
MAX_STROKES = 10000


def clamp(value, low, high):
    return max(low, min(high, value))


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Invalid coordinate or thickness.")
    return value


@dataclass
class Point:
    x: float
    y: float
    pressure: float = 1.0
    # Relative Bézier offsets move with their anchor. None uses the original
    # automatic tangent, so existing documents retain their exact centerline.
    handle_in: tuple = None
    handle_out: tuple = None
    # Relative scalar controls for the thickness polynomial. None retains
    # linear anchor pressure in existing strokes.
    pressure_in: float = None
    pressure_out: float = None
    # Independent diameter/base-width profile. Pressure remains the tablet
    # input for opacity/flow and other native sensors. None is legacy behavior.
    thickness: float = None
    thickness_in: float = None
    thickness_out: float = None


@dataclass
class Stroke:
    points: list
    width: float = 8.0
    color: str = "#202020"
    opacity: float = 1.0
    kind: str = "curve"
    minimum: float = 0.0
    taper_start: float = 0.0
    taper_end: float = 0.0
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    brush: dict = None

    def data(self):
        result = {"id": self.uid, "points": [[p.x, p.y, p.pressure] for p in self.points],
                "width": self.width, "color": self.color, "opacity": self.opacity,
                "kind": self.kind, "minimum": self.minimum,
                "taper_start": self.taper_start, "taper_end": self.taper_end}
        if self.brush is not None:
            result["brush"] = copy.deepcopy(self.brush)
        if any(p.handle_in is not None or p.handle_out is not None for p in self.points):
            result["handles"] = [[list(p.handle_in) if p.handle_in is not None else None,
                                  list(p.handle_out) if p.handle_out is not None else None]
                                 for p in self.points]
        if any(p.pressure_in is not None or p.pressure_out is not None for p in self.points):
            result['pressure_handles']=[[p.pressure_in,p.pressure_out] for p in self.points]
        if any(p.thickness is not None for p in self.points):
            result['thickness_profile'] = [[p.thickness, p.thickness_in, p.thickness_out] for p in self.points]
        return result

    @classmethod
    def from_data(cls, data):
        raw = data["points"]
        if not raw or len(raw) > MAX_POINTS:
            raise ValueError("Invalid number of points.")
        points = [Point(finite(p[0]), finite(p[1]), clamp(finite(p[2]), 0, 2)) for p in raw]
        if "handles" in data:
            handles = data["handles"]
            if not isinstance(handles, list) or len(handles) != len(points):
                raise ValueError("Invalid number of handles.")
            for point, pair in zip(points, handles):
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError("Invalid curve handles.")
                values = []
                for vector in pair:
                    if vector is None:
                        values.append(None)
                    elif isinstance(vector, (list, tuple)) and len(vector) == 2:
                        values.append(tuple(finite(v) for v in vector))
                    else:
                        raise ValueError("Invalid curve handle.")
                point.handle_in, point.handle_out = values
        if 'pressure_handles' in data:
            handles=data['pressure_handles']
            if not isinstance(handles,list) or len(handles)!=len(points):
                raise ValueError("Invalid quantity of thickness controls.")
            for point,pair in zip(points,handles):
                if not isinstance(pair,(list,tuple)) or len(pair)!=2:
                    raise ValueError("Invalid thickness controls.")
                point.pressure_in,point.pressure_out=(None if v is None else finite(v) for v in pair)
        if 'thickness_profile' in data:
            profile = data['thickness_profile']
            if not isinstance(profile, list) or len(profile) != len(points):
                raise ValueError("Invalid number of thicknesses.")
            for point, values in zip(points, profile):
                if not isinstance(values, (list, tuple)) or len(values) != 3:
                    raise ValueError("Invalid thickness profile.")
                if values[0] is None:
                    raise ValueError("Incomplete thickness profile.")
                point.thickness = finite(values[0])
                if not 0 <= point.thickness <= 20000:
                    raise ValueError("Point thickness out of range.")
                point.thickness_in, point.thickness_out = (None if v is None else finite(v) for v in values[1:])
        color = data.get("color", "#202020")
        uid = data["id"]
        if not re.fullmatch(r"[0-9a-f]{32}", uid):
            raise ValueError("Invalid stroke identifier.")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Invalid color.")
        brush = data.get("brush")
        if brush is not None:
            if not isinstance(brush, dict) or brush.get("engine") != "krita-native":
                raise ValueError("Invalid brush data.")
            if any(not isinstance(brush.get(k), str) for k in ("name", "filename", "xml")):
                raise ValueError("Invalid brush preset.")
            if len(brush["xml"]) > 4*1024*1024:
                raise ValueError("Brush preset too big.")
            brush = copy.deepcopy(brush)
            brush["flow"] = clamp(finite(brush.get("flow", 1)), 0, 1)
        return cls(points, clamp(finite(data.get("width", 8)), .1, 2000), color,
                   clamp(finite(data.get("opacity", 1)), 0, 1),
                   "line" if data.get("kind") == "line" else "curve",
                   clamp(finite(data.get("minimum", 0)), 0, 1),
                   clamp(finite(data.get("taper_start", 0)), 0, 1),
                   clamp(finite(data.get("taper_end", 0)), 0, 1), uid, brush)


def load_strokes(data):
    if not isinstance(data, list) or len(data) > MAX_STROKES:
        raise ValueError("Invalid number of strokes.")
    strokes = [Stroke.from_data(s) for s in data]
    if len({s.uid for s in strokes}) != len(strokes):
        raise ValueError("Repeated stroke identifiers.")
    return strokes


def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def segment_distance(p, a, b):
    dx, dy = b.x - a.x, b.y - a.y
    den = dx * dx + dy * dy
    t = clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / den, 0, 1) if den else 0
    return math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy), t


def simplify(points, tolerance, pressure_scale):
    """Iterative RDP that also retains meaningful changes in pen pressure."""
    if len(points) < 3:
        return copy.deepcopy(points)
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        best, index = tolerance, None
        for i in range(a + 1, b):
            d, t = segment_distance(points[i], points[a], points[b])
            expected = points[a].pressure * (1 - t) + points[b].pressure * t
            error = max(d, abs(points[i].pressure - expected) * pressure_scale)
            if error > best:
                best, index = error, i
        if index is not None:
            keep.add(index)
            stack.extend(((a, index), (index, b)))
    return [copy.copy(points[i]) for i in sorted(keep)]


def geometry_key(stroke):
    return (stroke.kind, tuple((p.x, p.y, p.pressure, p.handle_in, p.handle_out,p.pressure_in,p.pressure_out,
                               p.thickness, p.thickness_in, p.thickness_out)
                              for p in stroke.points))


def thickness_factor(point):
    return point.pressure if point.thickness is None else point.thickness


def set_point_thickness(stroke, index, pixels):
    """Set a diameter without modifying the captured tablet pressure."""
    point = stroke.points[index]
    point.thickness = clamp(finite(pixels), 0, 2000)/stroke.width


def freeze_thickness(stroke, convert=None):
    """Materialize both scalar controls before editing, preserving legacy data."""
    for point in stroke.points:
        if point.thickness is None:
            point.thickness = max(0, convert(point.pressure)) if convert else point.pressure
            for side in ('in', 'out'):
                control = getattr(point, 'pressure_'+side)
                if control is not None:
                    setattr(point, 'thickness_'+side,
                            convert(point.pressure+control)-point.thickness if convert else control)


def transform_stroke(stroke, coefficients):
    a,b,c,d,tx,ty=(finite(v) for v in coefficients)
    determinant=a*d-b*c
    if abs(determinant)<1e-10:raise ValueError("The stroke scale cannot be zero.")
    width=stroke.width*math.sqrt(abs(determinant))
    if not .1<=width<=2000:raise ValueError("The transformed thickness exceeds the range of 0.1 to 2000 px.")
    if stroke.kind == 'curve':
        # Chord-dependent automatic tangents are not invariant under unequal
        # X/Y scaling. Freeze their current controls before the affine mapping.
        vectors = [(handle_vector(stroke,i,'in'),handle_vector(stroke,i,'out'))
                   for i in range(len(stroke.points))]
        for point,(incoming,outgoing) in zip(stroke.points,vectors):
            if point.handle_in is None:point.handle_in=incoming
            if point.handle_out is None:point.handle_out=outgoing
    for p in stroke.points:
        p.x,p.y=a*p.x+c*p.y+tx,b*p.x+d*p.y+ty
        for side in ('handle_in','handle_out'):
            handle=getattr(p,side)
            if handle is not None:setattr(p,side,(a*handle[0]+c*handle[1],b*handle[0]+d*handle[1]))
    stroke.width=width


def segment_controls(stroke, index):
    """Cubic controls equivalent to the legacy chord-aware Hermite curve."""
    points = stroke.points
    a, b = points[index:index+2]
    previous, following = points[max(0, index-1)], points[min(len(points)-1, index+2)]
    length = distance(a, b)
    d0, d2 = distance(previous, a), distance(b, following)
    f0 = length/(d0+length) if d0+length else 0
    f2 = length/(length+d2) if length+d2 else 0
    out = a.handle_out if a.handle_out is not None else ((b.x-previous.x)*f0/3, (b.y-previous.y)*f0/3)
    incoming = b.handle_in if b.handle_in is not None else ((a.x-following.x)*f2/3, (a.y-following.y)*f2/3)
    pc=a.pressure+a.pressure_out if a.pressure_out is not None else (2*a.pressure+b.pressure)/3
    pd=b.pressure+b.pressure_in if b.pressure_in is not None else (a.pressure+2*b.pressure)/3
    c, d = Point(a.x+out[0], a.y+out[1],pc), Point(b.x+incoming[0], b.y+incoming[1],pd)
    if a.thickness is not None or b.thickness is not None:
        wa, wb = thickness_factor(a), thickness_factor(b)
        c.thickness = wa+a.thickness_out if a.thickness_out is not None else (2*wa+wb)/3
        d.thickness = wb+b.thickness_in if b.thickness_in is not None else (wa+2*wb)/3
    return a, c, d, b


def handle_vector(stroke, index, side):
    if stroke.kind != "curve":
        return None
    p = stroke.points[index]
    if side == "in" and index > 0:
        control = segment_controls(stroke, index-1)[2]
    elif side == "out" and index < len(stroke.points)-1:
        control = segment_controls(stroke, index)[1]
    else:
        return None
    return control.x-p.x, control.y-p.y


def lerp_point(a, b, t):
    point = Point(a.x*(1-t)+b.x*t, a.y*(1-t)+b.y*t,
                  a.pressure*(1-t)+b.pressure*t)
    if a.thickness is not None or b.thickness is not None:
        point.thickness = thickness_factor(a)*(1-t)+thickness_factor(b)*t
    return point


def cubic_point(controls, t):
    a, c, d, b = controls
    u = 1-t
    point = Point(u**3*a.x+3*u*u*t*c.x+3*u*t*t*d.x+t**3*b.x,
                 u**3*a.y+3*u*u*t*c.y+3*u*t*t*d.y+t**3*b.y,
                 max(0,u**3*a.pressure+3*u*u*t*c.pressure+3*u*t*t*d.pressure+t**3*b.pressure))
    if any(p.thickness is not None for p in controls):
        point.thickness = max(0, sum(v*thickness_factor(p) for v, p in zip(
            (u**3, 3*u*u*t, 3*u*t*t, t**3), controls)))
    return point


def segment_point(stroke, index, t):
    if stroke.kind == "line":
        return lerp_point(stroke.points[index], stroke.points[index+1], t)
    return cubic_point(segment_controls(stroke, index), t)


def closest_location(stroke, point):
    """Nearest segment and curve parameter, including loops made by handles."""
    best = (float("inf"), 0, 0.0)
    for index in range(len(stroke.points)-1):
        if stroke.kind == "line":
            d, t = segment_distance(point, stroke.points[index], stroke.points[index+1])
            if d < best[0]:
                best = d, index, t
            continue
        controls = segment_controls(stroke, index)
        length = sum(distance(a, b) for a, b in zip(controls, controls[1:]))
        steps = max(12, min(128, math.ceil(length/8)))
        a = controls[0]
        local_best = (float("inf"), 0)
        for j in range(steps):
            b = cubic_point(controls, (j+1)/steps)
            d, t = segment_distance(point, a, b)
            if d < local_best[0]:
                local_best = d, (j+t)/steps
            a = b
        lo, hi = max(0, local_best[1]-1/steps), min(1, local_best[1]+1/steps)
        for _ in range(24):
            left, right = (2*lo+hi)/3, (lo+2*hi)/3
            if distance(point, cubic_point(controls, left)) <= distance(point, cubic_point(controls, right)):
                hi = right
            else:
                lo = left
        t = (lo+hi)/2
        candidates = [(distance(point, cubic_point(controls, v)), index, v) for v in (0, t, 1)]
        best = min(best, *candidates)
    return best


def insert_point(stroke, index, t):
    """Split a cubic with de Casteljau without moving any existing curve."""
    if t <= 1e-5:
        return index
    if t >= 1-1e-5:
        return index+1
    if len(stroke.points) >= MAX_POINTS:
        raise ValueError("This stroke has reached the point limit.")
    t = clamp(t, 0, 1)
    if stroke.kind == "line":
        point = segment_point(stroke, index, t)
    else:
        # Inserting an anchor changes automatic neighbors. Freeze all existing
        # controls before splitting so the rest of the stroke stays identical.
        controls = [segment_controls(stroke, i) for i in range(len(stroke.points)-1)]
        for i, (a, c, d, b) in enumerate(controls):
            a.handle_out = c.x-a.x, c.y-a.y
            b.handle_in = d.x-b.x, d.y-b.y
            a.pressure_out=c.pressure-a.pressure
            b.pressure_in=d.pressure-b.pressure
            if a.thickness is not None:
                a.thickness_out = c.thickness-a.thickness
                b.thickness_in = d.thickness-b.thickness
        a, c, d, b = controls[index]
        q0, q1, q2 = lerp_point(a, c, t), lerp_point(c, d, t), lerp_point(d, b, t)
        r0, r1 = lerp_point(q0, q1, t), lerp_point(q1, q2, t)
        point = lerp_point(r0, r1, t)
        a.handle_out = q0.x-a.x, q0.y-a.y
        b.handle_in = q2.x-b.x, q2.y-b.y
        point.handle_in = r0.x-point.x, r0.y-point.y
        point.handle_out = r1.x-point.x, r1.y-point.y
        a.pressure_out=q0.pressure-a.pressure
        b.pressure_in=q2.pressure-b.pressure
        point.pressure_in=r0.pressure-point.pressure
        point.pressure_out=r1.pressure-point.pressure
        if point.thickness is not None:
            a.thickness_out = q0.thickness-a.thickness
            b.thickness_in = q2.thickness-b.thickness
            point.thickness_in = r0.thickness-point.thickness
            point.thickness_out = r1.thickness-point.thickness
    stroke.points.insert(index+1, point)
    return index+1


def samples(stroke):
    """Automatic/manual cubic interpolation, including exact imported thickness."""
    points = stroke.points
    if len(points) < 2:
        return [copy.copy(p) for p in points]
    out = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        length = distance(a, b)
        controls = segment_controls(stroke, i) if stroke.kind == "curve" else None
        if controls and (a.handle_out is not None or b.handle_in is not None):
            length = sum(distance(c, d) for c, d in zip(controls, controls[1:]))
        steps = max(2, min(128, math.ceil(length / 2)))
        for j in range(steps):
            t = j / steps
            if stroke.kind == "line":
                point = lerp_point(a, b, t)
            else:
                point = cubic_point(controls, t)
            out.append(point)
    out.append(copy.copy(points[-1]))
    return out


def outline(stroke):
    center = samples(stroke)
    if not center:
        return []
    # Remove zero-length tangents while preserving the last pressure at a location.
    clean = [center[0]]
    for p in center[1:]:
        if distance(p, clean[-1]) > 1e-7:
            clean.append(p)
        else:
            clean[-1] = p
    center = clean
    if len(center) == 1:
        p = center[0]
        radius = stroke.width * (stroke.minimum+(1-stroke.minimum)*thickness_factor(p)) / 2
        return [(p.x + math.cos(i*math.tau/32)*radius,
                 p.y + math.sin(i*math.tau/32)*radius) for i in range(32)]
    lengths = [0.0]
    for a, b in zip(center, center[1:]):
        lengths.append(lengths[-1] + distance(a, b))
    total = lengths[-1]
    left, right, angles, radii = [], [], [], []
    for i, p in enumerate(center):
        a, b = center[max(0, i - 1)], center[min(len(center) - 1, i + 1)]
        angle = math.atan2(b.y - a.y, b.x - a.x)
        pressure = stroke.minimum + (1 - stroke.minimum) * thickness_factor(p)
        progress = lengths[i] / total
        taper = (1-stroke.taper_start) + stroke.taper_start*min(1, progress/.15)
        taper *= (1-stroke.taper_end) + stroke.taper_end*min(1, (1-progress)/.15)
        radius = stroke.width * pressure * taper / 2
        nx, ny = -math.sin(angle)*radius, math.cos(angle)*radius
        left.append((p.x+nx, p.y+ny))
        right.append((p.x-nx, p.y-ny))
        angles.append(angle)
        radii.append(radius)
    def cap(p, angle, radius):
        return [(p.x+math.cos(angle-i*math.pi/12)*radius,
                 p.y+math.sin(angle-i*math.pi/12)*radius) for i in range(1, 12)]
    return (left + cap(center[-1], angles[-1]+math.pi/2, radii[-1]) +
            list(reversed(right)) + cap(center[0], angles[0]-math.pi/2, radii[0]))


def path_data(stroke):
    poly = outline(stroke)
    if not poly:
        return ""
    return "M " + " L ".join("{:.5f},{:.5f}".format(x, y) for x, y in poly) + " Z"


def svg(strokes, width, height, x_res=72.0, y_res=72.0, native_renderer=None):
    # Krita shapes use points. Explicit physical size preserves document pixels
    # at any document resolution, including 300 DPI and non-square pixels.
    physical_w, physical_h = width * 72 / x_res, height * 72 / y_res
    paths = []
    for s in strokes:
        if s.brush:
            if native_renderer is None:
                raise ValueError("The native brush needs the Krita renderer.")
            paths.append(native_renderer.svg_image(s))
        else:
            paths.append('<g id="lw_{id}"><path id="lw_{id}_outline" fill="{color}" fill-opacity="{opacity}" d="{path}"/></g>'.format(
                id=s.uid, color=escape(s.color), opacity=s.opacity, path=path_data(s)))
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{:.8f}pt" height="{:.8f}pt" '
            'viewBox="0 0 {} {}">{}</svg>').format(physical_w, physical_h, width, height, "".join(paths))


class History:
    def __init__(self, strokes, limit=80):
        self.limit = limit
        self.undo_stack = []
        self.redo_stack = []
        self.current = copy.deepcopy(strokes)
        self._current_data = [s.data() for s in self.current]

    def commit(self, strokes):
        values = [s.data() for s in strokes]
        if values == self._current_data:
            return
        previous = {s.uid:(s,record) for s,record in zip(self.current,self._current_data)}
        # History owns immutable snapshots. Reuse untouched strokes between
        # steps; callers always receive independent copies from undo/redo.
        current = [previous[s.uid][0] if s.uid in previous and previous[s.uid][1] == value
                   else copy.deepcopy(s) for s,value in zip(strokes,values)]
        self.undo_stack.append(self.current)
        self.undo_stack = self.undo_stack[-self.limit:]
        self.current = current
        self._current_data = values
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.current)
            self.current = self.undo_stack.pop()
            self._current_data = [s.data() for s in self.current]
        return copy.deepcopy(self.current)

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.current)
            self.current = self.redo_stack.pop()
            self._current_data = [s.data() for s in self.current]
        return copy.deepcopy(self.current)
