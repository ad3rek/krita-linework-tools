# SPDX-License-Identifier: GPL-3.0-or-later
"""Krita SVG bridge. Only explicitly recorded plugin shapes are replaced."""
import hashlib
import json
import math
from PyQt5.QtCore import QByteArray
from .model import load_strokes, svg
from .native_brush import refresh_layer, shape_write

ANNOTATION = "org.felipe.linework.v1"


def layer_id(layer):
    return layer.uniqueId().toString()


def metadata(document):
    raw = bytes(document.annotation(ANNOTATION))
    if not raw:
        return {"version": 6, "layers": {}}
    data = json.loads(raw.decode("utf-8"))
    if data.get("version") not in (1, 2, 3, 4, 5, 6) or not isinstance(data.get("layers"), dict):
        raise ValueError("Dados Linework de versão não suportada.")
    return data


def digest(shape):
    return hashlib.sha256(shape.toSvg().encode("utf-8")).hexdigest()


def matches_shape(shape, name, record):
    if digest(shape) == record['shapes'][name]:
        return True
    state = record.get('poses', {}).get(name)
    if state is None:
        return False
    from .transforms import canonical_digest, coefficients
    from .native_brush import shape_frame
    # Saving several groups assigns anonymous child paths document-wide IDs.
    # On reopening, only those IDs/serialization precision may differ. Match
    # geometry, image/style payload and pose instead of accepting all SVG edits.
    return (all(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-8)
                for a, b in zip(coefficients(shape_frame(shape)), state['frame'])) and
            canonical_digest(shape, state.get('payload_version', 1)) == state['payload'])


def check_layer(layer, record, verify=True):
    expected = record.get("shapes", {})
    actual = {s.name(): s for s in layer.shapes()}
    for name, fingerprint in expected.items():
        if name not in actual or (verify and not matches_shape(actual[name], name, record)):
            raise ValueError("Esta camada foi alterada pelas ferramentas nativas do Krita. "
                             "Crie uma nova camada Linework para preservar essas alterações.")
    return actual


def document_geometry(document):
    return [document.width(), document.height(), document.xRes(), document.yRes()]


def check_geometry(document, record):
    current = document_geometry(document)
    previous = record.get("geometry", current)
    # .kra rounds imported PNG resolution; tolerate that serialization precision.
    valid = previous[:2] == current[:2] and all(math.isclose(a, b, rel_tol=1e-5, abs_tol=.001)
                                              for a, b in zip(previous[2:], current[2:]))
    if not valid:
        raise ValueError("O tamanho ou a resolução do documento mudou após criar os traços. "
                         "Preserve a camada existente e crie uma nova camada Linework.")


def read_layer(document, layer, view=None):
    if layer is None or layer.type() != "vectorlayer":
        return None
    record = metadata(document)["layers"].get(layer_id(layer))
    if record is None:
        return None
    if view is not None:
        from .transforms import sync_layer
        if sync_layer(document, layer, view):
            record = metadata(document)["layers"][layer_id(layer)]
    check_geometry(document, record)
    check_layer(layer, record)
    return load_strokes(record.get("strokes", []))


def write_layer(document, layer, strokes, native_renderer=None, trusted=False):
    data = metadata(document)
    new_layer = layer is None
    if new_layer:
        layer = document.createVectorLayer("Linework — traços editáveis")
        active = document.activeNode()
        parent = active.parentNode() if active else document.rootNode()
        if parent is None:
            parent = document.rootNode()
        if not parent.addChildNode(layer, active):
            raise RuntimeError("Não foi possível criar a camada vetorial.")
    if layer.locked():
        raise ValueError("Desbloqueie a camada antes de aplicar.")
    key = layer_id(layer)
    previous = data["layers"].get(key, {"strokes": [], "shapes": {}})
    check_geometry(document, previous)
    current = check_layer(layer, previous, verify=not trusted)
    old_strokes = {s["id"]: s for s in previous["strokes"]}
    retained = {"lw_"+s.uid for s in strokes if old_strokes.get(s.uid) == s.data()
                and "lw_"+s.uid in previous["shapes"]}
    changed = [s for s in strokes if "lw_"+s.uid not in retained]
    if trusted:
        # The active native Linework tool owns input. Check every shape we will
        # replace/delete; untouched images keep their original fingerprints so
        # any outside edits are still detected when the layer is rebound.
        for name, fingerprint in previous["shapes"].items():
            if name not in retained and not matches_shape(current[name], name, previous):
                raise ValueError("Esta camada foi alterada pelas ferramentas nativas do Krita.")
    # Painting/PNG preparation may yield to Qt while the old shapes are stable.
    # Only the import, replacements and final metadata/projection commit enter
    # the native outer wait; other plugins never observe partially changed lists.
    try:
        markup = svg(changed, document.width(), document.height(), document.xRes(),
                     document.yRes(), native_renderer) if changed else None
    except Exception:
        if new_layer:
            layer.remove()
        raise
    with shape_write(layer):
        added = []
        try:
            # Import first, validate, then remove only the previous owned shapes.
            if changed:
                added = list(layer.addShapesFromSvg(markup))
                if len(added) != len(changed):
                    raise RuntimeError("O Krita não importou todos os traços vetoriais.")
                for shape, stroke in zip(added, changed):
                    shape.setName("lw_" + stroke.uid)
            for name in previous["shapes"]:
                if name in retained:
                    continue
                if not current[name].remove():
                    raise RuntimeError("Não foi possível substituir um traço da camada.")
        except Exception:
            for shape in added:
                shape.remove()
            if new_layer:
                layer.remove()
            raise
        document.waitForDone()
        owned = {name: current[name] for name in retained}
        owned.update({s.name(): s for s in added})
        # Keep the same layer order when editing an older stroke.
        first_z = min((s.zIndex() for s in owned.values()), default=0)
        for i, stroke in enumerate(strokes):
            owned["lw_"+stroke.uid].setZIndex(first_z+i)
        from .transforms import shape_state
        poses = previous.get('poses', {})
        data["layers"][key] = {"strokes": [s.data() for s in strokes],
                                "geometry": document_geometry(document),
                                "poses": {name: poses[name] if name in retained and name in poses else shape_state(s)
                                          for name, s in owned.items()},
                                "shapes": {name: previous["shapes"][name] if name in retained else digest(s)
                                           for name, s in owned.items()}}
        # Older versions must refuse these documents instead of discarding handles.
        data["version"] = 6
        document.setAnnotation(ANNOTATION, "Linhas e pressão editáveis do plugin Linework",
                               QByteArray(json.dumps(data, ensure_ascii=False).encode("utf-8")))
        document.setActiveNode(layer)
        document.setModified(True)
        document.refreshProjection()
        refresh_layer(layer)
        document.waitForDone()
        return layer
