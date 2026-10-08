#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce the CC BY 4.0 test raster from David Revoy's original JPEG."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path, help='Original JPEG linked in docs/ARTWORK.md')
    parser.add_argument('--output', type=Path, default=root/'examples/pepper-lineart.png')
    args = parser.parse_args()
    source = json.loads((root/'docs/validation/artwork-source.json').read_text())
    if hashlib.sha256(args.original.read_bytes()).hexdigest() != source['original_sha256']:
        parser.error('The original does not match the documented source SHA-256.')
    image = Image.open(args.original).crop(tuple(source['changes']['crop_xyxy']))
    resampling = getattr(Image, 'Resampling', Image).LANCZOS
    image = image.resize(tuple(source['changes']['dimensions']), resampling).convert('L')
    levels = source['changes']['levels']
    black, white = levels['input_black'], levels['input_white']
    lookup = [round(255*max(0, min(1, (v-black)/(white-black)))) for v in range(256)]
    image.point(lookup).save(args.output)
    print('Saved grayscale lineart with levels:', args.output)
    print('SHA-256:', hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
