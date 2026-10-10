# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform paths shared by the GUI bridge and worker vectorizer."""
import ctypes
import os
import json
import platform
import re
from pathlib import Path

_DLL_DIRECTORIES = []
KRITA_DOWNLOAD = 'https://krita.org/en/download/'


def bridge_target(version):
    system = platform.system()
    root = Path(__file__).with_name('native')
    manifest = json.loads((root/'bridges.json').read_text())
    targets = manifest.get(system, {})
    match = re.fullmatch(r'(\d+\.\d+\.\d+(?:\.\d+)?)(?:[- ].*)?', version)
    number = match.group(1) if match else None
    if number not in targets:
        supported = ', '.join(targets) or '(none for '+system+')'
        raise ValueError(
            "Incompatible Krita version for this Linework package.\nDetected: Krita "+(version or '(unknown)')+'.\n'
            'Supported on '+system+': Krita '+supported+'.\n'
            'Use the matching '+system+' x86_64 Linework package.\n'
            'Krita downloads: '+KRITA_DOWNLOAD+'\n'
            'Other versions require a rebuilt and tested native bridge.')
    return number, targets[number]


def load_native_bridge(version):
    # Reject unknown versions before resolving or loading any native code.
    number, target = bridge_target(version)
    path = library_path('native', number)
    try:
        library = ctypes.PyDLL(str(path))
    except OSError as exc:
        raise ValueError(
            "Could not load the Linework native bridge:\n"+str(path)+'\n'
            'Detected: Krita '+version+'.\n'+str(exc)+'\n'
            'Reinstall the matching platform package and restart Krita.') from exc
    # New bridges declare their build target. Legacy 5.2.14 bridges predate this.
    if number != '5.2.14':
        try:
            compiled = library.linework_bridge_krita_version
            compiled.restype = ctypes.c_char_p
            if compiled().decode() != number:
                raise ValueError("The installed Linework DLL was built for a different Krita version: "+str(path))
            qt = library.linework_bridge_qt_version
            qt.restype = ctypes.c_char_p
            if int(qt().decode().split('.')[0]) != target['qt']:
                raise ValueError("The installed Linework DLL uses a different Qt major: "+str(path))
        except AttributeError as exc:
            raise ValueError("The installed Linework DLL is outdated or incorrect: "+str(path)+
                             '\nReinstall the matching platform package and restart Krita.') from exc
    return library


def application_directory():
    from .qt import QCoreApplication
    return QCoreApplication.applicationDirPath()


def library_path(component, version=None):
    system = platform.system()
    machine = platform.machine().lower()
    if machine not in ('x86_64', 'amd64') or system not in ('Linux', 'Windows'):
        raise ValueError("This build requires Linux or Windows x86_64.")
    root = Path(__file__).with_name('native')
    if component == 'native' and version is not None:
        _, target = bridge_target(version)
        path = root/target['file']
    else:
        path = root/('linework_'+component+'.dll' if system == 'Windows' else 'liblinework_'+component+'.so')
    if system == 'Windows':
        # Python 3.8+ uses restricted DLL search. Keep directory handles alive.
        # Qt supplies Krita's bin directory even when sys.executable is unusual.
        if not _DLL_DIRECTORIES:
            for directory in (root, Path(application_directory())):
                _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))
    return path
