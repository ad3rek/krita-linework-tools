#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run GUI regressions in a separate Krita, with isolated resources and IPC."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib
import zipfile


def performance_fixture(checkout, output):
    with zipfile.ZipFile(checkout/'examples/pepper-linework.kra') as archive:
        data=json.loads(archive.read('Unnamed/annotations/org.felipe.linework.v1'))
    (output/'fixture.json').write_text(json.dumps(next(iter(data['layers'].values()))['strokes']))


def blank_png(path, size=900):
    def chunk(kind, data):
        return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data))
    row = b'\0'+b'\xff\xff\xff\0'*size
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!2I5B', size, size, 8, 6, 0, 0, 0))+
                     chunk(b'IDAT', zlib.compress(row*size))+chunk(b'IEND', b''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('probe', choices=['cc_lineart', 'multi_point', 'smoothing', 'color', 'stroke_lifecycle', 'eraser_topology', 'performance', 'interface', 'animation', 'layer_lifecycle', 'thickness_handles', 'localization', 'animation_close', 'brush_size', 'autosave_recovery', 'unified_vectorize'])
    parser.add_argument('--output', type=Path, help='Directory for reports, captures and test documents')
    parser.add_argument('--language', default='en', help='Krita interface language for this isolated run')
    args = parser.parse_args()
    autosave_config = 'AutoSaveInterval=2\n' if args.probe == 'autosave_recovery' else ''
    checkout = Path(__file__).resolve().parents[2]
    output = (args.output or checkout/'work/gui-results'/args.probe).resolve()
    for directory in ('docs/validation', 'docs/images', 'examples'):
        (output/directory).mkdir(parents=True, exist_ok=True)
    for command in ('krita', 'xvfb-run'):
        if not shutil.which(command):
            parser.error(command+' is required (Linux / Krita 5.2.14 / compatible Qt 5 ABI).')
    report = output/'docs/validation'/({'cc_lineart': 'cc-lineart.json',
        'multi_point': 'multi-point.json', 'smoothing': 'smoothing.json', 'color': 'color.json',
        'stroke_lifecycle': 'stroke-lifecycle.json', 'eraser_topology': 'eraser-topology.json', 'performance':'performance.json', 'interface':'interface.json', 'animation':'animation.json', 'layer_lifecycle':'layer-lifecycle.json', 'thickness_handles':'thickness-handles.json', 'localization':'localization.json', 'animation_close':'animation-close.json', 'brush_size':'brush-size.json', 'autosave_recovery':'autosave-recovery.json', 'unified_vectorize':'unified-vectorize.json'}[args.probe])
    report.unlink(missing_ok=True)
    (output/'phase.json').unlink(missing_ok=True)
    (output/'stack.log').unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='linework-gui-') as tmp:
        base = Path(tmp)
        config, data, ipc = base/'config', base/'data', base/'ipc'
        config.mkdir(); data.mkdir(); ipc.mkdir()
        env = dict(os.environ, XDG_CONFIG_HOME=str(config), XDG_DATA_HOME=str(data),
            TMPDIR=str(ipc), LINEWORK_TEST_ROOT=str(output), QT_LOGGING_RULES='*.debug=false', LINEWORK_TEST_LANGUAGE=args.language)
        env['PYTHONPATH'] = '/usr/lib/x86_64-linux-gnu/krita-python-libs'+os.pathsep+env.get('PYTHONPATH', '')
        config.joinpath('kritarc').write_text('CanvasOnlyActive=false\nuseOpenGL=false\n'+autosave_config+'\n[python]\nenable_linework=true\nenable_probe=true\n')
        (config/'klanguageoverridesrc').write_text('[Language]\nkrita='+args.language+'\n')
        pykrita = data/'krita/pykrita'
        pykrita.mkdir(parents=True)
        shutil.copytree(checkout/'linework', pykrita/'linework',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('linework.desktop', 'linework.action'):
            shutil.copy2(checkout/name, pykrita/name)
        (pykrita/'probe').mkdir()
        shutil.copy2(Path(__file__).with_name(args.probe+'.py'), pykrita/'probe/__init__.py')
        (pykrita/'probe.desktop').write_text('[Desktop Entry]\nType=Service\nServiceTypes=Krita/PythonPlugin\nX-KDE-Library=probe\nX-Python-2-Compatible=false\nName=Isolated Linework test\n')
        if args.probe == 'cc_lineart':
            fixture = output/'examples/pepper-lineart.png'
            shutil.copy2(checkout/'examples/pepper-lineart.png', fixture)
        else:
            fixture = output/'examples/blank.png'
            blank_png(fixture)
        if args.probe == 'performance': performance_fixture(checkout,output)
        with (output/'krita.log').open('w') as log:
            process = subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1600x1100x24',
                'timeout', '1200s' if args.probe == 'cc_lineart' else ('900s' if args.probe == 'animation' else '300s'), 'krita', '--nosplash', str(fixture)],
                env=env, stdout=log, stderr=subprocess.STDOUT)
    if not report.exists():
        raise SystemExit('No test report; see '+str(output/'krita.log'))
    results = json.loads(report.read_text())
    results['application_exit_code'] = process.returncode
    if process.returncode != 0:
        results['result'] = 'fail'
        results['failure_stage'] = 'application_exit'
    report.write_text(json.dumps(results, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(results, indent=2, ensure_ascii=False))
    raise SystemExit(0 if process.returncode == 0 and results.get('result') == 'pass' else 1)


if __name__ == '__main__':
    main()
