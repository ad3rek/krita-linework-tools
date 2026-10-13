# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('frame_payload', Path(__file__).resolve().parents[1] / 'linework/frame_payload.py')
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


class SharedBrushTests(unittest.TestCase):
    def setUp(self):
        brush = {'engine': 'krita-native', 'xml': '<preset>colour é &amp; flow</preset>' * 100,
                 'name': 'Brush', 'filename': 'brush.kpp', 'flow': .8}
        self.record = {'geometry': [2048, 2048, 72, 72],
                       'strokes': [{'id': str(i), 'points': [[i, 2, .4]], 'brush': copy.deepcopy(brush)} for i in range(20)],
                       'appearances': {'0': {'png': 'original-pixels', 'bounds': [0, 0, 3, 4]}},
                       'fingerprint': 'unchanged'}

    def test_roundtrip_preserves_geometry_pixels_and_all_brush_fields(self):
        original = copy.deepcopy(self.record)
        compact = payload.compact_record(self.record)
        self.assertEqual(len(compact['brushes']), 1)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(original)) / 4)
        decoded = payload.expand_record(json.loads(json.dumps(compact)))
        self.assertEqual(decoded, original)
        self.assertEqual(self.record, original)
        decoded['strokes'][0]['brush']['flow'] = .2
        self.assertEqual(decoded['strokes'][1]['brush']['flow'], .8)
        self.assertEqual(next(iter(compact['brushes'].values()))['flow'], .8)

    def test_same_xml_with_different_flow_stays_distinct(self):
        self.record['strokes'][3]['brush']['flow'] = .2
        compact = payload.compact_record(self.record)
        self.assertEqual(len(compact['brushes']), 2)
        self.assertEqual(payload.expand_record(compact), self.record)

    def test_mixed_native_and_unbrushed_strokes_keep_order(self):
        self.record['strokes'][5].pop('brush')
        self.assertEqual(payload.expand_record(payload.compact_record(self.record)), self.record)

    def test_legacy_records_are_readable_and_compaction_is_idempotent(self):
        self.assertEqual(payload.expand_record(self.record), self.record)
        compact = payload.compact_record(self.record)
        self.assertEqual(payload.compact_record(compact), compact)

    def test_corrupt_references_and_unknown_encoding_fail(self):
        for change in ('missing', 'mixed', 'unknown', 'unversioned', 'wrong_type'):
            record = copy.deepcopy(payload.compact_record(self.record))
            if change == 'missing': record['brushes'].clear()
            if change == 'mixed': record['strokes'][0]['brush'] = {}
            if change == 'unknown': record['encoding'] = 'future-format'
            if change == 'unversioned': record.pop('encoding')
            if change == 'wrong_type': record['strokes'][0]['brush_ref'] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                payload.expand_record(record)


if __name__ == '__main__':
    unittest.main()
