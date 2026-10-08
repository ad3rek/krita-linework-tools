#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-build for official Krita 5.2.14 Windows using LLVM-MinGW 18 UCRT."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--krita-source', required=True, type=Path)
    parser.add_argument('--sdk-prefix', required=True, type=Path)
    parser.add_argument('--krita-bin', required=True, type=Path)
    parser.add_argument('--toolchain', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    source = args.krita_source.resolve()
    sdk = args.sdk_prefix.resolve()/'include'
    # Do not resolve the compiler symlink: its target triple comes from argv[0].
    compiler = args.toolchain.absolute()/'bin/x86_64-w64-mingw32-clang++'
    tools = args.toolchain.absolute()/'bin'
    qt, kf = sdk, sdk/'KF5'
    if not (source/'libs/libkis/Node.h').exists() or not (qt/'QtCore/qconfig.h').exists():
        parser.error('Official Krita 5.2.14 sources and the Windows Qt 5.15.7 SDK are required.')
    with tempfile.TemporaryDirectory(prefix='linework-windows-') as tmp:
        generated = Path(tmp)
        exports = ['kritaglobal','kritaimage','kritaui','kritalibkis','kritapigment',
            'kritaflake','kritaresources','kritaresourcecache','kritalibbrush',
            'kritalibpaintop','kritastore','kritawidgetutils','kritacommand',
            'kritawidgets','kritapsdutils']
        for name in exports:
            (generated/(name+'_export.h')).write_text('#include <QtCore/qglobal.h>\n#define '+
                name.upper()+'_EXPORT Q_DECL_IMPORT\n#define '+name.upper()+'_NO_EXPORT\n')
        (generated/'KoConfig.h').write_text('#pragma once\n')
        for template in source.rglob('config*.h.cmake'):
            text = '\n'.join('/* '+line+' */' if line.startswith('#cmakedefine') else line
                for line in template.read_text().splitlines())
            (generated/template.name.replace('.cmake','')).write_text(text+'\n')
        libraries = ['libkritalibkis','libkritaui','libkritaimage','libkritaflake',
            'libkritapigment','libkritaresources','libkritaglobal','libkritacommand',
            'Qt5Core','Qt5Gui','Qt5Widgets','Qt5Xml']
        imports = []
        for name in libraries:
            dll = args.krita_bin.resolve()/(name+'.dll')
            dump = subprocess.check_output([str(tools/'llvm-readobj'),'--coff-exports',str(dll)],text=True)
            symbols = re.findall(r'^  Name: (.+)$',dump,re.M)
            definition = generated/(name+'.def')
            definition.write_text('LIBRARY '+name+'.dll\nEXPORTS\n'+'\n'.join(symbols)+'\n')
            archive = generated/(name+'.dll.a')
            subprocess.run([str(tools/'llvm-dlltool'),'-m','i386:x86-64','-d',str(definition),
                            '-l',str(archive)],check=True)
            imports.append(str(archive))
        includes = [generated,sdk,kf,source/'libs/ui']
        includes += sorted({p.parent for p in (source/'libs').rglob('*.h') if '/tests/' not in str(p)})
        includes += sorted(p for p in qt.iterdir() if p.is_dir())
        includes += sorted(p for p in kf.iterdir() if p.is_dir())
        subprocess.run([str(compiler),'-std=c++17','-fno-operator-names','-DNOMINMAX',
            '-shared','-O2','-Wno-deprecated-declarations',str(root/'bridge.cpp'),
            *[f'-I{p}' for p in includes],*imports,'-o',str(root/'linework_native.dll')],check=True)
        port = root/'opentoonz'
        # Upstream exports templates before their specializations. Clang rejects
        # that Windows-only ordering; this private DLL needs no template exports.
        # Omit only export instantiations in a generated header; math is untouched.
        geometry = (port/'upstream/toonz/sources/include/tgeometry.h').read_text()
        geometry = re.sub(r'^template class DVAPI .*;\n', '', geometry, flags=re.M)
        (generated/'tgeometry.h').write_text(geometry)
        sources = [root/'vectorize.cpp']+[port/'core'/('tcenterline'+name+'.cpp')
            for name in ('polygonizer','skeletonizer','adjustments','tostrokes','colors')]
        sources.append(port/'upstream/toonz/sources/common/tgeometry/tgeometry.cpp')
        subprocess.run([str(compiler),'-std=c++17','-DTGEOMETRY_EXPORTS','-D_USE_MATH_DEFINES','-DNOMINMAX','-O2','-shared',
            '-I'+str(port/'compat'),'-I'+str(generated),'-I'+str(port/'upstream/toonz/sources/include'),'-I'+str(port/'core'),
            *map(str,sources),'-o',str(root/'linework_vectorize.dll')],check=True)
    print('Built:',root/'linework_native.dll',root/'linework_vectorize.dll')


if __name__ == '__main__':
    main()
