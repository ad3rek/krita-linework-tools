# SPDX-License-Identifier: GPL-3.0-or-later
"""Adopt native affine transforms without replacing selected shape objects."""
from .i18n import tr
import json
import math
from collections import OrderedDict
from .qt import QByteArray
from .qt import QTransform
from .model import load_strokes, outline, transform_stroke
from .native_brush import shape_frame, shape_canonical, render_shape, NativeBrushRenderer
from .svg_fingerprint import payload_digest

_legacy_states = OrderedDict()


def legacy_states(document, layer):
    key=(document.rootNode().uniqueId().toString(),layer.uniqueId().toString())
    states=_legacy_states.setdefault(key,{})
    _legacy_states.move_to_end(key)
    while len(_legacy_states)>32:_legacy_states.popitem(last=False)
    return states


def coefficients(matrix):
    return [matrix.m11(), matrix.m12(), matrix.m21(), matrix.m22(), matrix.dx(), matrix.dy()]


def canonical_digest(shape, version=2):
    # SVG writers quantize coordinates and regenerate anonymous IDs. Normalize
    # only numeric geometry attributes; embedded PNG and styles remain exact.
    return payload_digest(shape_canonical(shape), version)


def shape_state(shape):
    return {'frame': coefficients(shape_frame(shape)), 'payload': canonical_digest(shape), 'payload_version': 2}


def legacy_frame(document, shape, stroke):
    pixel_to_flake = QTransform.fromScale(72/document.xRes(),72/document.yRes())
    # Existing native brushes use a named group with document-pixel children.
    if '<image' in shape.toSvg():
        return pixel_to_flake
    # Older smooth strokes were bare normalized path shapes. Reconstruct their
    # original unit frame from the exact five-decimal outline serialized by us.
    polygon = [(round(x,5),round(y,5)) for x,y in outline(stroke)]
    left,top = min(x for x,y in polygon),min(y for x,y in polygon)
    right,bottom = max(x for x,y in polygon),max(y for x,y in polygon)
    return (QTransform.fromScale(right-left,bottom-top)*
            QTransform.fromTranslate(left,top)*pixel_to_flake)


def pending_signature(document, layer):
    from .storage import metadata, layer_id
    record = metadata(document)['layers'].get(layer_id(layer))
    if record is None:return None
    states = record.get('poses',{})
    cached=legacy_states(document,layer)
    actual = {s.name():s for s in layer.shapes()}
    pending = []
    for name in record['shapes']:
        shape = actual.get(name)
        if shape is None:return ('missing',name)
        frame = coefficients(shape_frame(shape))
        previous = states.get(name,{}).get('frame')
        if previous is None:
            # Legacy records need one digest pass to detect changes/migrate.
            from .storage import digest
            if digest(shape) != record['shapes'][name]:pending.append((name,tuple(frame)))
            elif name not in cached or cached[name][0]!=record['shapes'][name]:
                cached[name]=(record['shapes'][name],shape_state(shape))
        elif any(not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8) for a,b in zip(frame,previous)):
            pending.append((name,tuple(frame)))
    return tuple(pending)


def sync_layer(document, layer, view):
    from .storage import metadata, layer_id, digest, check_geometry, ANNOTATION
    if layer is None or layer.type() != 'vectorlayer':return False
    data = metadata(document);key=layer_id(layer);record=data['layers'].get(key)
    if record is None:return False
    check_geometry(document,record)
    actual = {s.name():s for s in layer.shapes()}
    strokes = load_strokes(record['strokes']);states=record.get('poses',{})
    cached=legacy_states(document,layer)
    changed=[];new_states=dict(states)
    pixel_to_flake = QTransform.fromScale(72/document.xRes(),72/document.yRes())
    inverse_pixel = pixel_to_flake.inverted()[0]
    for stroke in strokes:
        name='lw_'+stroke.uid;shape=actual.get(name)
        if shape is None:raise ValueError(tr("A Linework stroke was removed by the native tool."))
        old_state=states.get(name)
        current=shape_frame(shape)
        if old_state and all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10)
                             for a,b in zip(coefficients(current),old_state['frame'])):
            continue
        if digest(shape) == record['shapes'][name]:
            if name not in new_states:
                new_states[name]=shape_state(shape)
                cached[name]=(record['shapes'][name],new_states[name])
            continue
        if old_state is None and name in cached and cached[name][0]==record['shapes'][name]:
            old_state=cached[name][1]
        if old_state:
            if canonical_digest(shape, old_state.get('payload_version', 1)) != old_state['payload']:
                raise ValueError(tr("The SVG geometry or style has changed. Linework supports moving, rotating and resizing the line."))
            previous=QTransform(*old_state['frame'])
        else:
            previous=legacy_frame(document,shape,stroke)
        inverse,ok=previous.inverted()
        if not ok:raise ValueError(tr("The previous stroke transformation is invalid."))
        delta=pixel_to_flake*inverse*current*inverse_pixel
        if old_state is None and all(math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8)
               for a,b in zip(coefficients(delta),[1,0,0,1,0,0])):
            raise ValueError(tr("The appearance of the stroke was changed without a position or scale transformation."))
        transform_stroke(stroke,coefficients(delta));changed.append((name,shape,stroke))
    if not changed:
        # Remember legacy baselines without marking a previously clean file as
        # modified: the next real write persists poses together with the strokes.
        return False
    if layer.locked():raise ValueError(tr("Unlock the layer before updating the transformation."))
    renderer=NativeBrushRenderer(view)
    try:
        # Resolve presets and prepare all images before touching any shape.
        for name,shape,stroke in changed:
            if stroke.brush:renderer.render(stroke)
        for name,shape,stroke in changed:
            render_shape(document,layer,shape,stroke,renderer)
            new_states[name]=shape_state(shape)
            record['shapes'][name]=digest(shape)
    finally:renderer.close()
    record['strokes']=[s.data() for s in strokes];record['poses']=new_states
    data['version']=5
    document.setAnnotation(ANNOTATION,tr("Linework plugin editable lines and pressure"),
                           QByteArray(json.dumps(data,ensure_ascii=False).encode('utf-8')))
    document.setModified(True);document.refreshProjection();document.waitForDone()
    return True
