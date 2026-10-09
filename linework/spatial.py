# SPDX-License-Identifier: GPL-3.0-or-later
"""Conservative grid candidates; exact picking/erasing stays in the editor."""
import math
from .model import segment_controls, thickness_factor


def intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


class Grid:
    def __init__(self, cell_size=64, maximum_cells=256):
        self.cell_size = cell_size
        self.maximum_cells = maximum_cells
        self.bounds = {}; self.cells = {}; self.membership = {}; self.large = set()

    def extent(self, box):
        return tuple(math.floor(v/self.cell_size) for v in box)

    def insert(self, key, box):
        self.remove(key); self.bounds[key] = box
        x0, y0, x1, y1 = self.extent(box)
        if (x1-x0+1)*(y1-y0+1) > self.maximum_cells:
            self.large.add(key); return
        occupied = [(x,y) for x in range(x0,x1+1) for y in range(y0,y1+1)]
        self.membership[key] = occupied
        for cell in occupied: self.cells.setdefault(cell,set()).add(key)

    def remove(self, key):
        self.bounds.pop(key, None); self.large.discard(key)
        for cell in self.membership.pop(key, ()):
            bucket = self.cells[cell]; bucket.discard(key)
            if not bucket: del self.cells[cell]

    def query(self, box):
        x0, y0, x1, y1 = self.extent(box)
        # Large selections/long sweeps must not enumerate unbounded empty cells.
        if (x1-x0+1)*(y1-y0+1) > max(16, len(self.cells)*2):
            candidates = self.bounds
        else:
            candidates = set(self.large)
            for x in range(x0,x1+1):
                for y in range(y0,y1+1): candidates.update(self.cells.get((x,y), ()))
        return {key for key in candidates if intersects(self.bounds[key], box)}


def stroke_bounds(stroke):
    controls = list(stroke.points)
    if stroke.kind == 'curve':
        for index in range(len(stroke.points)-1):
            controls.extend(segment_controls(stroke,index)[1:3])
    # Cubics lie inside their control hull, including automatic tangents.
    # The scalar hull also bounds overshooting diameter controls. Tapers only
    # shrink this envelope. Exact outline and center tests follow the query.
    radius = stroke.width*max(0, *(abs(stroke.minimum+(1-stroke.minimum)*thickness_factor(p))
                                  for p in controls))/2
    return (min(p.x for p in controls)-radius, min(p.y for p in controls)-radius,
            max(p.x for p in controls)+radius, max(p.y for p in controls)+radius)


class SpatialIndex:
    def __init__(self, strokes):
        self.strokes = {s.uid:s for s in strokes}
        self.order = {s.uid:i for i,s in enumerate(strokes)}
        self.paths = Grid(); self.anchors = Grid(); self.point_keys = {}
        for stroke in strokes: self.update(stroke)

    def update(self, stroke):
        self.remove(stroke.uid); self.strokes[stroke.uid] = stroke
        keys = {(stroke.uid,i) for i in range(len(stroke.points))}
        self.point_keys[stroke.uid] = keys
        for uid,i in keys:
            p = stroke.points[i]; self.anchors.insert((uid,i),(p.x,p.y,p.x,p.y))
        self.paths.insert(stroke.uid,stroke_bounds(stroke))

    def anchors_in(self, box): return self.anchors.query(box)
    def strokes_in(self, box): return self.paths.query(box)

    def remove(self, uid):
        self.strokes.pop(uid,None); self.paths.remove(uid)
        for key in self.point_keys.pop(uid,()): self.anchors.remove(key)
