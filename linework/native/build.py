#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the bridge against the official Krita 5.2.14 headers and local Qt 5 SDK."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser(description='Compila a ponte nativa para Krita 5.2.14.')
    parser.add_argument('--krita-source',required=True,type=Path)
    parser.add_argument('--sdk-prefix',default=Path('/usr'),type=Path,
                        help='Prefixo contendo include/Qt5 e include/KF5; padrão /usr')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    source=args.krita_source.resolve();sdk=args.sdk_prefix.resolve()/'include'
    qt=sdk/'x86_64-linux-gnu/qt5';kf=sdk/'KF5'
    if not (source/'libs/libkis/Node.h').exists() or not qt.exists() or not kf.exists():
        parser.error('São necessários os fontes Krita 5.2.14 e os headers Qt 5 / KF5.')
    with tempfile.TemporaryDirectory(prefix='linework-build-') as tmp:
        generated=Path(tmp)
        exports=['kritaglobal','kritaimage','kritaui','kritalibkis','kritapigment',
            'kritaflake','kritaresources','kritaresourcecache','kritalibbrush',
            'kritalibpaintop','kritastore','kritawidgetutils','kritacommand','kritawidgets',
            'kritapsdutils']
        for name in exports:
            (generated/(name+'_export.h')).write_text('#include <QtCore/qglobal.h>\n#define '+
                name.upper()+'_EXPORT Q_DECL_IMPORT\n#define '+name.upper()+'_NO_EXPORT\n')
        (generated/'KoConfig.h').write_text('#pragma once\n')
        for template in source.rglob('config*.h.cmake'):
            text='\n'.join('/* '+line+' */' if line.startswith('#cmakedefine') else line
                for line in template.read_text().splitlines())
            (generated/template.name.replace('.cmake','')).write_text(text+'\n')
        includes=[generated,sdk,qt,kf,source/'libs/ui']
        includes+=sorted({p.parent for p in (source/'libs').rglob('*.h') if '/tests/' not in str(p)})
        includes+=sorted(p for p in qt.iterdir() if p.is_dir())
        includes+=sorted(p for p in kf.iterdir() if p.is_dir())
        command=['g++','-std=c++17','-fno-operator-names','-fPIC','-shared','-O2',
            '-fvisibility=hidden','-Wno-deprecated-declarations',str(root/'bridge.cpp'),
            '-o',str(root/'liblinework_native.so')]
        command += [f'-I{p}' for p in includes]
        command += ['-L/usr/lib/x86_64-linux-gnu','-Wl,--no-undefined']
        for name in ['kritalibkis','kritaui','kritaimage','kritaflake','kritapigment',
                     'kritaresources','kritaglobal','kritacommand']:
            command += ['-l:lib'+name+'.so.19']
        for name in ['Qt5Core','Qt5Gui','Qt5Widgets','Qt5Xml']:
            command += ['-l:lib'+name+'.so.5']
        subprocess.run(command,check=True)
    print('Ponte compilada:',root/'liblinework_native.so')


if __name__=='__main__':main()
