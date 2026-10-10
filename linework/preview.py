# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, lazy copies of committed stroke appearances, including reopened PNGs."""
from .i18n import tr
import base64
from collections import OrderedDict
import xml.etree.ElementTree as ET
from .qt import QRectF
from .qt import QImage


class SavedAppearanceCache:
    def __init__(self):
        self.images = OrderedDict()
        self.bytes = 0

    def forget(self, uid):
        old = self.images.pop(uid, None)
        if old:
            self.bytes -= old[1].sizeInBytes()

    def clear(self):
        self.images.clear()
        self.bytes = 0

    def get(self, document, layer, stroke, frame=None, payload=None):
        if not stroke.brush:
            return None
        if stroke.uid in self.images:
            self.images.move_to_end(stroke.uid)
            return self.images[stroke.uid]
        if layer.type() == 'paintlayer':
            from .animation import record, appearance
            bounds, image = appearance(payload or record(document, layer, frame), stroke)
            self.images[stroke.uid] = (bounds, image)
            self.bytes += image.sizeInBytes()
            while self.bytes > 64*1024*1024 and len(self.images) > 1:
                _, old = self.images.popitem(last=False)
                self.bytes -= old[1].sizeInBytes()
            return bounds, image
        shape = next((s for s in layer.shapes() if s.name() == "lw_"+stroke.uid), None)
        if shape is None:
            raise ValueError(tr("The original stroke is no longer on the layer."))
        # Decode the saved pixels rather than replaying a possibly random brush.
        fragment = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'+shape.toSvg()+'</svg>'
        images = [e for e in ET.fromstring(fragment).iter() if e.tag.rsplit('}', 1)[-1] == 'image']
        if len(images) != 1:
            raise ValueError(tr("This stroke’s saved appearance is not supported."))
        href = images[0].get('{http://www.w3.org/1999/xlink}href', images[0].get('href', ''))
        if not href.startswith('data:image/png;base64,'):
            raise ValueError(tr("The stroke image is not embedded in the document."))
        image = QImage.fromData(base64.b64decode(href.split(',', 1)[1]), 'PNG')
        if image.isNull():
            raise ValueError(tr("Unable to read the recorded appearance of the stroke."))
        from .native_brush import shape_image_bounds
        bounds = shape_image_bounds(shape)
        bounds = QRectF(bounds.x()*document.xRes()/72, bounds.y()*document.yRes()/72,
                        bounds.width()*document.xRes()/72, bounds.height()*document.yRes()/72)
        self.images[stroke.uid] = (bounds, image)
        self.bytes += image.sizeInBytes()
        while self.bytes > 64*1024*1024 and len(self.images) > 1:
            _, old = self.images.popitem(last=False)
            self.bytes -= old[1].sizeInBytes()
        return bounds, image
