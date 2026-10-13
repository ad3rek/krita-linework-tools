# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned frame records with one immutable definition per native brush."""
import copy
import hashlib
import json

ENCODING = 'shared-brushes-v1'
DOCUMENT_VERSION = 8


def compact_record(record):
    """Do not change the editable model or the caller's record."""
    if record.get('encoding') == ENCODING:
        return record
    brushes, strokes = {}, []
    for original in record['strokes']:
        stroke = dict(original)
        brush = stroke.pop('brush', None)
        if brush is not None:
            key = hashlib.sha256(json.dumps(brush, ensure_ascii=False, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()
            if key in brushes and brushes[key] != brush:
                raise ValueError('Conflicting Linework brush definitions.')
            brushes[key] = brush
            stroke['brush_ref'] = key
        strokes.append(stroke)
    return dict(record, encoding=ENCODING, brushes=brushes, strokes=strokes)


def expand_record(record):
    """Accept legacy records; reject missing references instead of losing brushes."""
    encoding = record.get('encoding')
    if encoding is None:
        if any('brush_ref' in stroke for stroke in record.get('strokes', ())):
            raise ValueError('Linework brush references have no encoding.')
        return record
    if encoding != ENCODING or not isinstance(record.get('brushes'), dict):
        raise ValueError('Unsupported Linework frame encoding.')
    brushes, strokes = record['brushes'], []
    for original in record['strokes']:
        stroke = dict(original)
        if 'brush_ref' in stroke:
            key = stroke.pop('brush_ref')
            if ('brush' in stroke or not isinstance(key, str) or
                    key not in brushes or not isinstance(brushes[key], dict)):
                raise ValueError('Invalid Linework brush reference.')
            # Brush settings are mutable on the model; each stroke owns its dict.
            # Immutable XML strings remain shared after this copy.
            stroke['brush'] = copy.deepcopy(brushes[key])
        strokes.append(stroke)
    expanded = dict(record, strokes=strokes)
    expanded.pop('encoding')
    expanded.pop('brushes')
    return expanded
