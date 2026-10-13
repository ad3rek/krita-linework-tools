# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('appearance_cache', Path(__file__).resolve().parents[1] / 'linework/appearance_cache.py')
cache_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache_module)


class Image:
    def __init__(self, value, size=10): self.value, self.size = value, size
    def sizeInBytes(self): return self.size


class AppearanceCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = cache_module.DecodedAppearanceCache(64)
        self.calls = []
        self.data = {'bounds': [0, 1, 2, 3], 'png': 'original'}
    def decode(self, value):
        self.calls.append(value)
        if value == 'invalid': raise ValueError('corrupt PNG')
        return Image(value)
    def get(self, owner='doc', uid='stroke', data=None):
        return self.cache.get(owner, uid, data or self.data, self.decode)

    def test_reopened_identical_content_reuses_decoded_pixels(self):
        first = self.get()[1]
        self.assertIs(self.get(data=dict(self.data))[1], first)
        self.assertEqual(self.calls, ['original'])

    def test_changed_png_bounds_and_undo_do_not_return_stale_images(self):
        self.get()
        moved = dict(self.data, bounds=[5, 6, 2, 3])
        self.assertEqual(self.get(data=moved)[0], tuple(moved['bounds']))
        self.assertEqual(self.get(data=dict(moved, png='edited'))[1].value, 'edited')
        self.assertEqual(self.get()[1].value, 'original')

    def test_document_identity_and_close_cleanup(self):
        self.get('first'); self.get('second')
        self.cache.clear_owner('first')
        self.assertNotIn(('first', 'stroke'), self.cache.entries)
        self.assertIn(('second', 'stroke'), self.cache.entries)
        self.assertEqual(self.cache.bytes, 18)
        self.cache.clear(); self.assertEqual(self.cache.bytes, 0)

    def test_lru_budget_and_single_oversize_appearance(self):
        self.get(uid='one'); self.get(uid='two'); self.get(uid='three'); self.get(uid='one'); self.get(uid='four')
        self.assertNotIn(('doc', 'two'), self.cache.entries)
        self.assertLessEqual(self.cache.bytes, self.cache.limit)
        self.cache.get('doc', 'big', self.data, lambda value: Image(value, 100))
        self.assertNotIn(('doc', 'big'), self.cache.entries)
        self.assertLessEqual(self.cache.bytes, self.cache.limit)

    def test_invalid_png_fails_without_poisoning_the_previous_entry(self):
        first = self.get()[1]
        with self.assertRaises(ValueError): self.get(data=dict(self.data, png='invalid'))
        self.assertIs(self.get()[1], first)


if __name__ == '__main__':
    unittest.main()
