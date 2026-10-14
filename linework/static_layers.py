# SPDX-License-Identifier: GPL-3.0-or-later
"""Create a static vector copy from an editable, single-frame Linework layer."""
from .i18n import tr
from .animation import bootstrap_layer, record, appearance
from .model import load_strokes
from .native_brush import NativeBrushRenderer
from .storage import write_layer


class SavedFrameRenderer:
    """Embed the existing PNG appearances without repainting their presets."""
    svg_image = NativeBrushRenderer.svg_image

    def __init__(self, payload):
        self.payload = payload

    def render(self, stroke):
        saved = self.payload['appearances'][stroke.uid]
        bounds, image = appearance(self.payload, stroke)
        return bounds, image, saved['png']


def static_copy(document, source, create_layer):
    if source is None or source.type() != 'paintlayer':
        raise ValueError(tr('Select an editable Linework paint layer first.'))
    info = bootstrap_layer(document, source)
    if not info.get('animated') or len(info['frames']) != 1:
        raise ValueError(tr('Static copies require one frame. Preserve animated layers for animation.'))
    payload = record(document, source)
    if payload is None:
        raise ValueError(tr('Select an editable Linework paint layer first.'))
    # Verify the original pixels before creating the destination. External
    # raster changes must never silently become a different editable drawing.
    strokes = load_strokes(payload['strokes'])
    layer = create_layer(document, 'vectorlayer')
    try:
        write_layer(document, layer, strokes, SavedFrameRenderer(payload))
        layer.setName(source.name()+tr(' — static copy'))
    except Exception:
        layer.remove()
        raise
    return layer
