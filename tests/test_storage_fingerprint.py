"""Regression for Krita dropping a zero-length closing line on .kra reload."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('svg_fingerprint', Path(__file__).resolve().parents[1]/'linework/svg_fingerprint.py')
fingerprint = importlib.util.module_from_spec(spec); spec.loader.exec_module(fingerprint)
digest = fingerprint.payload_digest

BEFORE = '<g id="lw_original" fill="none"><path id="outline" transform="translate(559,185)" fill="#757474" stroke-width="0" d="M10 33L10.3845 31.0656L0 0L10 33L10 33L10 33Z" sodipodi:nodetypes="ccccccc"/></g>'
AFTER = '<g id="lw_original" fill="none"><path id="path112" transform="translate(559,185)" fill="#757474" stroke-width="0" d="M10 33L10.3845 31.0656L0 0L10 33L10 33Z" sodipodi:nodetypes="cccccc"/></g>'

class StorageFingerprintTests(unittest.TestCase):
    def test_reloaded_zero_radius_cap_stays_editable(self):
        self.assertEqual(digest(BEFORE), digest(AFTER))
        self.assertNotEqual(digest(BEFORE, 1), digest(AFTER, 1))

    def test_changed_path_and_child_transform_still_detected(self):
        for altered in (AFTER.replace('L0 0', 'L2 0'), AFTER.replace('559,185', '560,185'),
                        AFTER.replace('L10 33Z', 'L11 33Z')):
            with self.subTest(svg=altered): self.assertNotEqual(digest(BEFORE), digest(altered))

    def test_color_opacity_and_embedded_bitmap_edits_still_detected(self):
        self.assertNotEqual(digest(BEFORE), digest(AFTER.replace('#757474', '#747474')))
        self.assertNotEqual(digest(BEFORE), digest(AFTER.replace('fill="none"', 'fill="none" opacity="0.5"')))
        bitmap = '<image xlink:href="data:image/png;base64,AbC123" width="100" height="80"/>'
        self.assertNotEqual(digest(bitmap), digest(bitmap.replace('AbC123', 'AbC124')))

    def test_existing_pose_fingerprint_is_preserved_by_version_one(self):
        self.assertEqual(digest(BEFORE, 1), '66dde3c146b235d382ba83ec4c5b8a5da0e4f24836d15410d565cd9330ad78fb')

if __name__ == '__main__': unittest.main()
