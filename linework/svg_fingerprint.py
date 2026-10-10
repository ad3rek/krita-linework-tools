# SPDX-License-Identifier: GPL-3.0-or-later
"""Fingerprint rendered SVG payloads across Krita save/load normalization."""
import hashlib
import re
import xml.etree.ElementTree as ET

_NUMBERS = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?')
_REPEATED_CLOSE = re.compile(r'(L[-+\d.eE]+\s+[-+\d.eE]+)(?:\1)+(?=[Zz]\s*$)')


def payload_digest(source, version=2):
    try:
        root = ET.fromstring('<svg xmlns:xlink="http://www.w3.org/1999/xlink" '
                            'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
                            'xmlns:krita="http://krita.org/namespaces/svg/krita">'+source+'</svg>')
    except ET.ParseError as exc:
        raise ValueError("The SVG structure of this stroke is not supported.") from exc
    for node in root.iter():
        node.attrib.pop('id', None)
        for key in ('d', 'transform', 'width', 'height', 'x', 'y'):
            if key in node.attrib:
                node.attrib[key] = _NUMBERS.sub(lambda m: str(round(float(m.group()), 4)+0.0), node.attrib[key])
        if version >= 2:
            # Krita drops an extra zero-length closing line and its editor-only
            # node-type hint on reload. Collapse repeated absolute closing Ls;
            # all other path commands, styles and embedded images stay checked.
            if 'd' in node.attrib:
                node.attrib['d'] = _REPEATED_CLOSE.sub(r'\1', node.attrib['d'])
            node.attrib.pop('{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}nodetypes', None)
    return hashlib.sha256(ET.tostring(root)).hexdigest()
