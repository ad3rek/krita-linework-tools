# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform paths shared by the GUI bridge and worker vectorizer."""
import os
import platform
from pathlib import Path

_DLL_DIRECTORIES = []


def library_path(component):
    system = platform.system()
    machine = platform.machine().lower()
    if machine not in ('x86_64', 'amd64') or system not in ('Linux', 'Windows'):
        raise ValueError('This build requires Linux or Windows x86_64.')
    root = Path(__file__).with_name('native')
    if system == 'Windows':
        # Python 3.8+ uses restricted DLL search. Keep directory handles alive.
        # Qt supplies Krita's bin directory even when sys.executable is unusual.
        if not _DLL_DIRECTORIES:
            from PyQt5.QtCore import QCoreApplication
            for directory in (root, Path(QCoreApplication.applicationDirPath())):
                _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))
        return root/('linework_'+component+'.dll')
    return root/('liblinework_'+component+'.so')
