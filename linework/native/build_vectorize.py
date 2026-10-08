#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the vendored OpenToonz centerline port, without the OpenToonz app or Qt."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parent
port=root/'opentoonz';include=port/'upstream/toonz/sources/include'
sources=[root/'vectorize.cpp']+[port/'core'/('tcenterline'+name+'.cpp')
    for name in ('polygonizer','skeletonizer','adjustments','tostrokes','colors')]
sources.append(port/'upstream/toonz/sources/common/tgeometry/tgeometry.cpp')
subprocess.run(['g++','-std=c++17','-DLINUX','-O2','-fPIC','-shared','-fvisibility=hidden',
    '-pthread','-I'+str(port/'compat'),'-I'+str(include),'-I'+str(port/'core'),
    *map(str,sources),'-Wl,--no-undefined','-o',str(root/'liblinework_vectorize.so')],check=True)
print('Vectorizer built:',root/'liblinework_vectorize.so')
