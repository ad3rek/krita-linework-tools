# SPDX-License-Identifier: GPL-3.0-or-later
"""Selection identities survive rerendering and stroke history replacement."""
class Selection:
    def __init__(self):
        self.strokes = set()
        self.points = set()
        self.primary = (None, -1)

    def clear(self):
        self.strokes.clear(); self.points.clear(); self.primary = (None, -1)

    def ids(self):
        return self.strokes | {uid for uid, index in self.points}

    def set_strokes(self, ids):
        self.strokes = set(ids); self.points.clear()
        self.primary = (next(iter(self.strokes), None), -1)

    def set_points(self, points):
        self.points = set(points); self.strokes.clear()
        self.primary = next(iter(self.points), (None, -1))

    def point_keys(self, strokes):
        result = set(self.points)
        for stroke in strokes:
            if stroke.uid in self.strokes:
                result.update((stroke.uid, i) for i in range(len(stroke.points)))
        return result

    def toggle_point(self, uid, index, strokes):
        if uid in self.strokes:
            self.strokes.remove(uid)
            stroke = next(s for s in strokes if s.uid == uid)
            self.points.update((uid, i) for i in range(len(stroke.points)))
        key = uid, index
        if key in self.points: self.points.remove(key)
        else: self.points.add(key)
        self.primary = key if key in self.points else next(iter(self.points), (next(iter(self.strokes), None), -1))

    def toggle_stroke(self, uid):
        if uid in self.ids():
            self.strokes.discard(uid)
            self.points = {(u, i) for u, i in self.points if u != uid}
        else: self.strokes.add(uid)
        self.primary = (uid, -1) if uid in self.strokes else next(iter(self.points), (next(iter(self.strokes), None), -1))

    def prune(self, strokes):
        lengths = {s.uid: len(s.points) for s in strokes}
        self.strokes.intersection_update(lengths)
        self.points = {(u, i) for u, i in self.points if u in lengths and 0 <= i < lengths[u]}
        uid, index = self.primary
        if uid not in self.ids(): self.primary = next(iter(self.points), (next(iter(self.strokes), None), -1))
        elif index >= lengths[uid]: self.primary = uid, -1
