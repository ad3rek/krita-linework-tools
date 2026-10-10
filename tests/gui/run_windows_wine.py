#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test the official Windows application under Wine in a disposable prefix."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from run import blank_png, performance_fixture


def windows_path(path):
    return 'Z:'+str(path.resolve()).replace('/', '\\')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('probe',choices=['cc_lineart','multi_point','smoothing','color','stroke_lifecycle','eraser_topology', 'performance', 'interface', 'animation', 'layer_lifecycle', 'thickness_handles', 'localization', 'animation_close', 'brush_size', 'autosave_recovery', 'unified_vectorize'])
    parser.add_argument('--krita-bin',required=True,type=Path,help='Official Windows Krita bin directory')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--wine-prefix',type=Path,help='Reuse a dedicated test prefix; do not use your normal Wine prefix')
    parser.add_argument('--reuse-resources',action='store_true',help='Keep the resource database in the dedicated test prefix between probes')
    parser.add_argument('--language', default='en', help='Krita interface language for this isolated run')
    args = parser.parse_args()
    autosave_config = 'AutoSaveInterval=2\n' if args.probe == 'autosave_recovery' else ''
    if args.reuse_resources and not args.wine_prefix:
        parser.error('--reuse-resources requires a dedicated --wine-prefix')
    checkout = Path(__file__).resolve().parents[2]
    output = (args.output or checkout/'work/windows-gui-results'/args.probe).resolve()
    for directory in ('docs/validation','docs/images','examples'):
        (output/directory).mkdir(parents=True,exist_ok=True)
    name = {'cc_lineart':'cc-lineart.json','multi_point':'multi-point.json','smoothing':'smoothing.json',
            'color':'color.json','stroke_lifecycle':'stroke-lifecycle.json','eraser_topology':'eraser-topology.json', 'performance':'performance.json', 'interface':'interface.json', 'animation':'animation.json', 'layer_lifecycle':'layer-lifecycle.json', 'thickness_handles':'thickness-handles.json', 'localization':'localization.json', 'animation_close':'animation-close.json', 'brush_size':'brush-size.json', 'autosave_recovery':'autosave-recovery.json', 'unified_vectorize':'unified-vectorize.json'}[args.probe]
    report = output/'docs/validation'/name
    report.unlink(missing_ok=True)
    (output/'phase.json').unlink(missing_ok=True)
    (output/'stack.log').unlink(missing_ok=True)
    command = ['xvfb-run','-a','-s','-screen 0 1600x1100x24']
    # Wine prefixes are large; keep them on the results filesystem, not /tmp.
    with tempfile.TemporaryDirectory(prefix='linework-wine-',dir=output) as temporary:
        base = Path(temporary)
        prefix = args.wine_prefix.resolve() if args.wine_prefix else base/'prefix'
        prefix.mkdir(parents=True,exist_ok=True)
        env = dict(os.environ,WINEPREFIX=str(prefix),WINEDEBUG='-all',
                   WINEARCH='win64',WINEDLLOVERRIDES='mscoree,mshtml=',
                   LINEWORK_TEST_ROOT=windows_path(output), LINEWORK_TEST_LANGUAGE=args.language,QT_LOGGING_RULES='*.debug=false')
        # Krita's Qt 5.15.7 startup cannot inherit the host Plasma workaround.
        env.pop('KDE_FULL_SESSION',None)
        if not (prefix/'system.reg').exists():
            try:
                with (output/'wineboot.log').open('w') as log:
                    subprocess.run(command+['timeout','90s','wine','wineboot.exe','-u'],env=env,
                                   stdout=log,stderr=subprocess.STDOUT,check=True)
            except subprocess.CalledProcessError:
                subprocess.run(['wineserver','-k'],env=env,check=False)
                raise
            # Boot services belong to the first Xvfb display, which has now closed.
            subprocess.run(['wineserver','-k'],env=env,check=True)
            subprocess.run(['wineserver','-w'],env=env,check=True)
        users = prefix/'drive_c/users'
        profiles = [p for p in users.iterdir() if (p/'AppData/Local').is_dir() and p.name != 'Public']
        if len(profiles) != 1:
            raise SystemExit('Expected one disposable Wine user profile.')
        # Remove leftovers from failed runs in this dedicated prefix before
        # launching. Rejecting a recovery dialog during startup can invalidate
        # Qt's active window and is unrelated to a canvas regression.
        temporary_files = profiles[0]/'AppData/Local/Temp'
        if temporary_files.resolve().is_relative_to(prefix):
            for autosave in temporary_files.glob('krita-*-autosave.kra'):
                autosave.unlink()
        # Empty Wine prefixes have no font faces for Krita's SVG text factory.
        fonts = Path('/usr/share/fonts/truetype/dejavu')
        if not fonts.exists():
            raise SystemExit('Install DejaVu fonts for this Wine test environment.')
        for font in fonts.glob('DejaVuSans*.ttf'):
            shutil.copy2(font,prefix/'drive_c/windows/Fonts'/font.name)
        resources = prefix/'linework-test-resources' if args.reuse_resources else base/'resources'
        pykrita = resources/'pykrita'
        if pykrita.exists(): shutil.rmtree(pykrita)
        pykrita.mkdir(parents=True)
        shutil.copytree(checkout/'linework',pykrita/'linework',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for file in ('linework.desktop','linework.action'):
            shutil.copy2(checkout/file,pykrita/file)
        (pykrita/'probe').mkdir()
        shutil.copy2(Path(__file__).with_name(args.probe+'.py'),pykrita/'probe/__init__.py')
        (pykrita/'probe.desktop').write_text('[Desktop Entry]\nType=Service\nServiceTypes=Krita/PythonPlugin\n'
            'X-KDE-Library=probe\nX-Python-2-Compatible=false\nName=Isolated Windows Linework test\n')
        (profiles[0]/'AppData/Local/kritarc').write_text('CanvasOnlyActive=false\nuseOpenGL=false\n'+autosave_config+
            'ResourceDirectory='+windows_path(resources).replace('\\','/')+'\n\n[python]\n'
            'enable_linework=true\nenable_probe=true\n')
        (profiles[0]/'AppData/Local/klanguageoverridesrc').write_text('[Language]\nkrita='+args.language+'\n')
        (profiles[0]/'AppData/Local/kritadisplayrc').write_text('OpenGLRenderer=none\nLogUsage=false\n')
        fixture = output/'examples'/('pepper-lineart.png' if args.probe == 'cc_lineart' else 'blank.png')
        if args.probe == 'cc_lineart':shutil.copy2(checkout/'examples/pepper-lineart.png',fixture)
        else:blank_png(fixture)
        if args.probe=='performance':performance_fixture(checkout,output)
        try:
            with (output/'krita.log').open('w') as log:
                result = subprocess.run(command+['timeout','1200s','wine',
                    windows_path(args.krita_bin/'krita.exe'),'--nosplash',windows_path(fixture)],
                    env=env,stdout=log,stderr=subprocess.STDOUT)
        finally:
            subprocess.run(['wineserver','-k'],env=env,check=False)
    if not report.exists():raise SystemExit('No test report; see '+str(output/'krita.log'))
    data = json.loads(report.read_text())
    data['application_exit_code'] = result.returncode
    if result.returncode != 0:
        data['result'] = 'fail'
        data['failure_stage'] = 'application_exit'
    report.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(data,indent=2,ensure_ascii=False))
    raise SystemExit(0 if result.returncode == 0 and data.get('result') == 'pass' else 1)


if __name__ == '__main__':
    main()
