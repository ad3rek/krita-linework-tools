# SPDX-License-Identifier: GPL-3.0-or-later
"""Swept eraser hit tests and event-rate-independent point width reduction."""
from .model import segment_distance, clamp


def segment_pair_distance(a, b, c, d):
    def cross(p, q, r): return (q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x)
    if (cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0 and
            max(min(a.x,b.x),min(c.x,d.x)) <= min(max(a.x,b.x),max(c.x,d.x)) and
            max(min(a.y,b.y),min(c.y,d.y)) <= min(max(a.y,b.y),max(c.y,d.y))):
        return 0
    return min(segment_distance(a,c,d)[0],segment_distance(b,c,d)[0],
               segment_distance(c,a,b)[0],segment_distance(d,a,b)[0])


def hit_center(center, start, end, radius):
    if len(center) == 1: return segment_distance(center[0],start,end)[0] <= radius
    return any(segment_pair_distance(start,end,a,b) <= radius for a,b in zip(center,center[1:]))


def point_weights(stroke, start, end, radius, strength, indices=None):
    if radius <= 0: return {}
    return {i: clamp(strength,0,1)*(1-(0 if distance/radius < 1e-8 else distance/radius))**2
            for i in (range(len(stroke.points)) if indices is None else indices)
            for p in (stroke.points[i],)
            if (distance := segment_distance(p,start,end)[0]) < radius}


def reduce_points(stroke, baseline, weights, coverage):
    """Use maximum coverage over a gesture; repeated stationary input is stable."""
    changed = False
    for index, weight in weights.items():
        previous = coverage.get(index, 0)
        if weight <= previous: continue
        coverage[index] = weight
        point, original = stroke.points[index], baseline.points[index]
        factor = 1-weight
        point.thickness = original.thickness*factor
        for side in ('in','out'):
            value = getattr(original,'thickness_'+side)
            setattr(point,'thickness_'+side,None if value is None else value*factor)
        changed = True
    return changed
