# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact a finished native brush path into editable cubic Béziers.

This is a post-process, not a replacement for Krita's smoothing engines.
Position, tablet pressure and an optional independent diameter are fitted
together. Imported paths and existing edited strokes are never passed here.
"""
import copy
import math
from .model import Point, segment_controls, thickness_factor

# Document pixels; small tips get a tighter positional tolerance below.
MODE_TOLERANCE = (.18, .25, .4, .55)
PRESSURE_TOLERANCE = .003
DIAMETER_TOLERANCE = .1
MAX_SAMPLES = 160000
MAX_FIT_WORK = 2400000


def _mix(a, b):
    return tuple((x+y)*.5 for x, y in zip(a, b))


def _error(a, b, limits):
    return max(math.hypot(a[0]-b[0], a[1]-b[1])/limits[0],
               *(abs(a[i]-b[i])/limits[i-1] for i in range(2, len(a))))


def _flatten(controls, limits):
    """Bound deviation from each chord using the cubic control polygon.

    Check parameter-linear controls, rather than just perpendicular XY
    distance: a straight curve can still contain a pressure pulse or vary
    its speed relative to pressure. The convex hull bounds all four channels.
    """
    stack = [controls]
    while stack:
        a, c, d, b = stack.pop()
        third = tuple((2*x+y)/3 for x, y in zip(a, b))
        second = tuple((x+2*y)/3 for x, y in zip(a, b))
        if max(_error(c, third, limits), _error(d, second, limits)) <= .08:
            yield b
        else:
            ac, cd, db = _mix(a, c), _mix(c, d), _mix(d, b)
            left, right = _mix(ac, cd), _mix(cd, db)
            middle = _mix(left, right)
            stack.extend(((middle, right, db, b), (a, ac, left, middle)))


def _direction(a, b):
    x, y = b[0]-a[0], b[1]-a[1]
    length = math.hypot(x, y)
    return (x/length, y/length) if length > 1e-12 else (0., 0.)


def _paired_error(a, b, limits, gradient):
    # Constrain pressure/diameter at the same visible location as well as at
    # the same parameter: small XY drift on a steep pressure ramp otherwise
    # moves the ramp along the path and can change its apparent thickness.
    position = math.hypot(a[0]-b[0], a[1]-b[1])
    return max(position/limits[0], *(
        (abs(a[k]-b[k])+position*gradient[k-2])/limits[k-1]
        for k in range(2, len(a))))


def _fit(data, start, end, lengths, limits):
    """Least-squares handles with native endpoint tangent directions."""
    a, b = data[start], data[end]
    span = lengths[end]-lengths[start]
    out = _direction(a, data[start+1])
    incoming = _direction(b, data[end-1])
    parameters = [(lengths[i]-lengths[start])/span for i in range(start, end+1)]
    # Scalar channels use the same curve parameter as the centerline.
    c = [0.]*len(a); d = [0.]*len(a)
    aa = ab = bb = 0.
    rhs_c = [0.]*len(a); rhs_d = [0.]*len(a)
    taa = tab = tbb = ta = tb = 0.
    for p, t in zip(data[start:end+1], parameters):
        u = 1-t; h1 = 3*u*u*t; h2 = 3*u*t*t
        aa += h1*h1; ab += h1*h2; bb += h2*h2
        for k in range(2, len(a)):
            residual = p[k]-u**3*a[k]-t**3*b[k]
            rhs_c[k] += h1*residual; rhs_d[k] += h2*residual
        vx, vy = h1*out[0], h1*out[1]
        wx, wy = h2*incoming[0], h2*incoming[1]
        rx = p[0]-(u**3+h1)*a[0]-(t**3+h2)*b[0]
        ry = p[1]-(u**3+h1)*a[1]-(t**3+h2)*b[1]
        taa += vx*vx+vy*vy; tab += vx*wx+vy*wy; tbb += wx*wx+wy*wy
        ta += vx*rx+vy*ry; tb += wx*rx+wy*ry
    determinant = taa*tbb-tab*tab
    alpha = (ta*tbb-tb*tab)/determinant if determinant > 1e-12 else -1.
    beta = (tb*taa-ta*tab)/determinant if determinant > 1e-12 else -1.
    if not 1e-8 <= alpha <= span*2 or not 1e-8 <= beta <= span*2:
        alpha = beta = math.dist(a[:2], b[:2])/3
    c[:2] = [a[k]+out[k]*alpha for k in range(2)]
    d[:2] = [b[k]+incoming[k]*beta for k in range(2)]
    determinant = aa*bb-ab*ab
    for k in range(2, len(a)):
        low = min(p[k] for p in data[start:end+1])
        high = max(p[k] for p in data[start:end+1])
        if determinant > 1e-12:
            c[k] = max(low, min(high, (rhs_c[k]*bb-rhs_d[k]*ab)/determinant))
            d[k] = max(low, min(high, (rhs_d[k]*aa-rhs_c[k]*ab)/determinant))
        else:
            c[k], d[k] = (2*a[k]+b[k])/3, (a[k]+2*b[k])/3
    controls = a, tuple(c), tuple(d), b
    worst, split = 0., (start+end)//2
    for index, t in enumerate(parameters[1:-1], start+1):
        u = 1-t
        q = tuple(u**3*a[k]+3*u*u*t*c[k]+3*u*t*t*d[k]+t**3*b[k] for k in range(len(a)))
        error = _error(data[index], q, limits)
        if error > worst: worst, split = error, index
    # A fitted curve can bulge between sample locations. Compare the complete
    # cubic restricted to each original chord; its control hull bounds the
    # continuous deviation, including pressure/diameter, not just anchors.
    for index in range(start, end):
        t0, t1 = parameters[index-start:index-start+2]
        q0, q1 = _value(controls, t0), _value(controls, t1)
        v0, v1 = _derivative(controls, t0), _derivative(controls, t1)
        h = (t1-t0)/3
        qc = tuple(q0[k]+h*v0[k] for k in range(len(a)))
        qd = tuple(q1[k]-h*v1[k] for k in range(len(a)))
        p0, p1 = data[index:index+2]
        chord = math.dist(p0[:2], p1[:2])
        gradient = tuple(abs(x-y)/chord if chord > 1e-12 else 0. for x, y in zip(p0[2:], p1[2:]))
        pc = tuple((2*x+y)/3 for x, y in zip(p0, p1))
        pd = tuple((x+2*y)/3 for x, y in zip(p0, p1))
        error = max(_paired_error(q0, p0, limits, gradient), _paired_error(qc, pc, limits, gradient),
                    _paired_error(qd, pd, limits, gradient), _paired_error(q1, p1, limits, gradient))
        if error > worst: worst, split = error, min(end-1, max(start+1, index))
    return controls, worst, split


def _value(controls, t):
    u = 1-t
    return tuple(sum(weight*p[k] for weight, p in zip(
        (u**3, 3*u*u*t, 3*u*t*t, t**3), controls)) for k in range(len(controls[0])))


def _derivative(controls, t):
    a, c, d, b = controls; u = 1-t
    return tuple(3*(u*u*(c[k]-a[k])+2*u*t*(d[k]-c[k])+t*t*(b[k]-d[k])) for k in range(len(a)))


def compact_stroke(stroke, mode):
    """Reduce new brush anchors atomically; return before/after counts.

    The caller retains the original live samples until painting is finished.
    Work limits and an unhelpful fit keep the original geometry intact.
    """
    before = len(stroke.points)
    if before < 3 or stroke.kind != 'curve': return before, before
    tolerance = min(MODE_TOLERANCE[max(0, min(3, int(mode)))], max(.03, stroke.width*.08))
    pressure_tolerance = min(PRESSURE_TOLERANCE, DIAMETER_TOLERANCE/max(1., stroke.width))
    limits = (tolerance, pressure_tolerance, DIAMETER_TOLERANCE)
    independent = any(p.thickness is not None for p in stroke.points)
    def vector(p):
        return (p.x, p.y, p.pressure)+( (thickness_factor(p)*stroke.width,) if independent else () )
    data = [vector(stroke.points[0])]; corners = [0]
    for index in range(before-1):
        controls = tuple(vector(p) for p in segment_controls(stroke, index))
        for p in _flatten(controls, limits):
            if p != data[-1]: data.append(p)
            if len(data) > MAX_SAMPLES: return before, before
        if index+1 < before-1:
            next_controls = tuple(vector(p) for p in segment_controls(stroke, index+1))
            incoming = _direction(controls[2], controls[3])
            outgoing = _direction(next_controls[0], next_controls[1])
            if incoming[0]*outgoing[0]+incoming[1]*outgoing[1] < .5 and incoming != (0., 0.) and outgoing != (0., 0.):
                corners.append(len(data)-1)
    corners.append(len(data)-1)
    if len(data) < 2: return before, before
    # Arc length in all retained channels also handles stationary pressure
    # changes and closed loops with coincident first/last coordinates.
    scales = (1., 1., tolerance/pressure_tolerance, tolerance/DIAMETER_TOLERANCE)
    lengths = [0.]
    for a, b in zip(data, data[1:]):
        lengths.append(lengths[-1]+math.sqrt(sum(((x-y)*scales[k])**2 for k, (x, y) in enumerate(zip(a, b)))))
    if lengths[-1] <= 1e-12: return before, before
    stack = list(reversed(list(zip(corners, corners[1:]))))
    fitted = []; work = 0
    while stack:
        start, end = stack.pop()
        if start == end: continue
        work += end-start+1
        if work > MAX_FIT_WORK: return before, before
        if end-start == 1:
            a, b = data[start], data[end]
            controls = a, tuple((2*x+y)/3 for x, y in zip(a, b)), tuple((x+2*y)/3 for x, y in zip(a, b)), b
            error = 0.
        else:
            controls, error, split = _fit(data, start, end, lengths, limits)
        # .08 of the allowance was used by flattening the source curve.
        if error <= .92:
            fitted.append(controls)
        else:
            # Keep pathological paths bounded by balancing extreme splits.
            split = max(start+max(1, (end-start)//10), min(end-max(1, (end-start)//10), split))
            stack.extend(((split, end), (start, split)))
    if not fitted or len(fitted)+1 >= before: return before, before
    points = []
    for a, c, d, b in fitted:
        if not points:
            first = copy.copy(stroke.points[0])
            first.handle_in = None; first.pressure_in = first.thickness_in = None
            points.append(first)
        first = points[-1]
        first.handle_out = c[0]-a[0], c[1]-a[1]
        first.pressure_out = c[2]-a[2]
        last = Point(b[0], b[1], b[2], handle_in=(d[0]-b[0], d[1]-b[1]), pressure_in=d[2]-b[2])
        if independent:
            first.thickness = a[3]/stroke.width; first.thickness_out = (c[3]-a[3])/stroke.width
            last.thickness = b[3]/stroke.width; last.thickness_in = (d[3]-b[3])/stroke.width
        points.append(last)
    stroke.points = points
    return before, len(points)
