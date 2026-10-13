# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded decoded pixels, validated against exact saved appearance content."""
from collections import OrderedDict


class DecodedAppearanceCache:
    def __init__(self, limit=64 * 1024 * 1024):
        self.limit = limit
        self.bytes = 0
        self.entries = OrderedDict()

    def discard(self, key):
        previous = self.entries.pop(key, None)
        if previous is not None:
            self.bytes -= previous[3]

    def clear_owner(self, owner):
        for key in tuple(self.entries):
            if key[0] == owner:
                self.discard(key)

    def clear(self):
        self.entries.clear()
        self.bytes = 0

    def get(self, owner, uid, data, decode):
        key = owner, uid
        bounds, png = tuple(data['bounds']), data['png']
        previous = self.entries.get(key)
        if previous is not None and previous[0] == bounds and previous[1] == png:
            self.entries.move_to_end(key)
            return bounds, previous[2]
        # Decode before replacing a valid entry; a corrupt record must fail.
        image = decode(png)
        self.discard(key)
        weight = image.sizeInBytes() + len(png)
        if weight <= self.limit:
            while self.entries and self.bytes + weight > self.limit:
                self.discard(next(iter(self.entries)))
            self.entries[key] = bounds, png, image, weight
            self.bytes += weight
        return bounds, image
