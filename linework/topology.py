# SPDX-License-Identifier: GPL-3.0-or-later
"""Point merging and endpoint joins, independent of Krita and Qt."""
import copy
from .model import (Point, MAX_POINTS, freeze_thickness, segment_controls,
                    lerp_point, distance)


def bake_minimum(stroke):
    """Put the minimum diameter into the profile before local width edits."""
    freeze_thickness(stroke)
    minimum = stroke.minimum
    if not minimum: return
    for point in stroke.points:
        point.thickness = minimum+(1-minimum)*point.thickness
        for side in ('in', 'out'):
            value = getattr(point, 'thickness_'+side)
            if value is not None: setattr(point, 'thickness_'+side, (1-minimum)*value)
    stroke.minimum = 0


def freeze_controls(stroke):
    """Keep existing segments unchanged when their neighbors/order change."""
    controls = [(a, lerp_point(a, b, 1/3), lerp_point(a, b, 2/3), b)
                if stroke.kind == 'line' else segment_controls(stroke, i)
                for i, (a, b) in enumerate(zip(stroke.points, stroke.points[1:]))]
    for a, c, d, b in controls:
        a.handle_out = c.x-a.x, c.y-a.y
        b.handle_in = d.x-b.x, d.y-b.y
        a.pressure_out = c.pressure-a.pressure
        b.pressure_in = d.pressure-b.pressure
        if a.thickness is not None:
            a.thickness_out = c.thickness-a.thickness
            b.thickness_in = d.thickness-b.thickness


def prepared(stroke, width=None):
    result = copy.deepcopy(stroke)
    bake_minimum(result); freeze_controls(result)
    if width is not None:
        ratio = result.width/width
        for point in result.points:
            point.thickness *= ratio
            if not 0 <= point.thickness <= 20000:
                raise ValueError('A espessura excede o intervalo suportado para o traço ativo.')
            for side in ('in', 'out'):
                value = getattr(point, 'thickness_'+side)
                if value is not None: setattr(point, 'thickness_'+side, value*ratio)
        result.width = width
    return result


def reversed_stroke(stroke):
    result = prepared(stroke)
    result.points.reverse()
    for point in result.points:
        point.handle_in, point.handle_out = point.handle_out, point.handle_in
        point.pressure_in, point.pressure_out = point.pressure_out, point.pressure_in
        point.thickness_in, point.thickness_out = point.thickness_out, point.thickness_in
    result.taper_start, result.taper_end = result.taper_end, result.taper_start
    return result


def merged_point(points, incoming, outgoing, active, position):
    if position not in ('center', 'active'):
        raise ValueError('Posição de mesclagem inválida.')
    if position == 'active': result = copy.deepcopy(active)
    else:
        result = Point(sum(p.x for p in points)/len(points),
                       sum(p.y for p in points)/len(points),
                       sum(p.pressure for p in points)/len(points),
                       thickness=sum(p.thickness for p in points)/len(points))
    # Exterior control points stay at their old absolute locations. Only the
    # two neighboring segments change when the anchors collapse.
    for source, side in ((incoming, 'in'), (outgoing, 'out')):
        vector = getattr(source, 'handle_'+side)
        setattr(result, 'handle_'+side, None if vector is None else
                (source.x+vector[0]-result.x, source.y+vector[1]-result.y))
        for channel in ('pressure', 'thickness'):
            value = getattr(source, channel+'_'+side)
            setattr(result, channel+'_'+side, None if value is None else
                    getattr(source, channel)+value-getattr(result, channel))
    return result


def merge_points(stroke, indices, active_index, position='center'):
    indices = sorted(set(indices))
    if (len(indices) < 2 or indices[0] < 0 or indices[-1] >= len(stroke.points) or
            indices != list(range(indices[0], indices[-1]+1))):
        raise ValueError('Selecione dois ou mais pontos consecutivos do mesmo traço.')
    if active_index not in indices: active_index = indices[-1]
    result = prepared(stroke)
    points = [result.points[i] for i in indices]
    point = merged_point(points, points[0], points[-1], result.points[active_index], position)
    result.points[indices[0]:indices[-1]+1] = [point]
    return result, indices[0]


def endpoint(stroke, index):
    return 0 <= index < len(stroke.points) and index in (0, len(stroke.points)-1)


def connect(a, b):
    a.handle_out = (b.x-a.x)/3, (b.y-a.y)/3
    b.handle_in = (a.x-b.x)/3, (a.y-b.y)/3
    for channel in ('pressure', 'thickness'):
        delta = (getattr(b, channel)-getattr(a, channel))/3
        setattr(a, channel+'_out', delta); setattr(b, channel+'_in', -delta)


def join_strokes(active, active_index, other, other_index, weld=False, position='center'):
    if active.uid == other.uid or not endpoint(active, active_index) or not endpoint(other, other_index):
        raise ValueError('Selecione uma ponta de cada um de dois traços.')
    count = len(active.points)+len(other.points)-int(weld)
    if count > MAX_POINTS: raise ValueError('A união excede o limite de pontos por traço.')
    a = prepared(active)
    b = prepared(other, active.width)
    if active_index == 0 and len(a.points) > 1: a = reversed_stroke(a)
    if other_index != 0: b = reversed_stroke(b)
    result = copy.deepcopy(a)  # Active preset, color, opacity, width and identity.
    result.kind = 'line' if a.kind == b.kind == 'line' else 'curve'
    result.taper_end = b.taper_end
    if weld:
        point = merged_point([a.points[-1], b.points[0]], a.points[-1], b.points[0], a.points[-1], position)
        result.points = a.points[:-1]+[point]+b.points[1:]
        selection = [len(a.points)-1]
    else:
        connect(a.points[-1], b.points[0])
        result.points = a.points+b.points
        selection = [len(a.points)-1, len(a.points)]
    return result, selection


def close_stroke(stroke):
    if len(stroke.points) < 2: raise ValueError('Este traço não possui duas pontas distintas.')
    if distance(stroke.points[0], stroke.points[-1]) < 1e-7: raise ValueError('Este traço já está fechado.')
    if len(stroke.points) >= MAX_POINTS: raise ValueError('O fechamento excede o limite de pontos.')
    result = prepared(stroke)
    first = copy.deepcopy(result.points[0])
    connect(result.points[-1], first)
    result.points.append(first)
    result.taper_start = result.taper_end = 0
    return result


def selection_kind(strokes, keys, primary, operation):
    grouped = {}
    by_id = {s.uid: s for s in strokes}
    for uid, index in keys:
        if uid not in by_id or not 0 <= index < len(by_id[uid].points):
            raise ValueError('Seleção de pontos inválida.')
        grouped.setdefault(uid, []).append(index)
    if len(keys) < 2: raise ValueError('Selecione os pontos com Shift+clique ou com o retângulo.')
    if operation == 'merge' and len(grouped) == 1:
        uid, indices = next(iter(grouped.items())); ordered = sorted(indices)
        if ordered == list(range(ordered[0], ordered[-1]+1)): return 'merge', uid, ordered
        raise ValueError('Mescle pontos consecutivos; use Unir pontas para fechar um traço.')
    if len(keys) != 2:
        raise ValueError('Para unir traços, selecione exatamente duas pontas.')
    pairs = sorted(keys)
    if any(not endpoint(by_id[uid], i) for uid, i in pairs):
        raise ValueError('A união precisa de pontos nas extremidades dos traços.')
    if len(grouped) == 1:
        stroke = by_id[pairs[0][0]]
        if distance(stroke.points[0], stroke.points[-1]) < 1e-7: raise ValueError('Este traço já está fechado.')
        return 'close', pairs[0][0], None
    active_key = primary if primary in keys else pairs[-1]
    other_key = next(p for p in pairs if p != active_key)
    return 'join', active_key, other_key
