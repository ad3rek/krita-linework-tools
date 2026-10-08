# SPDX-License-Identifier: GPL-3.0-or-later
"""Installation paths and native library selection across supported platforms."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def standalone(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlatformTests(unittest.TestCase):
    def test_windows_install_locations(self):
        installer = standalone('installer', ROOT/'install.py')
        with patch.object(installer.platform, 'system', return_value='Windows'), \
                patch.dict(os.environ, {'APPDATA':'C:/Users/test/AppData/Roaming',
                                        'LOCALAPPDATA':'C:/Users/test/AppData/Local'}):
            config, resources = installer.default_locations()
            self.assertEqual(config, Path('C:/Users/test/AppData/Local/kritarc'))
            self.assertEqual(resources, Path('C:/Users/test/AppData/Roaming/krita'))

    def test_linux_locations(self):
        installer = standalone('installer', ROOT/'install.py')
        with patch.object(installer.platform, 'system', return_value='Linux'), \
                patch.dict(os.environ, {'XDG_CONFIG_HOME':'/tmp/lw-config','XDG_DATA_HOME':'/tmp/lw-data'}):
            self.assertEqual(installer.default_locations(),
                             (Path('/tmp/lw-config/kritarc'),Path('/tmp/lw-data/krita')))

    def test_windows_install_preserves_previous_plugin_and_config(self):
        installer = standalone('installer', ROOT/'install.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);local = root/'local';roaming = root/'roaming'
            local.mkdir();resource = roaming/'krita';previous = resource/'pykrita/linework'
            previous.mkdir(parents=True);(previous/'old-marker').write_text('keep')
            config = local/'kritarc';original = '[other]\nkeep=true\n\n[python]\nenable_linework=false\nenable_other=true\n'
            config.write_text(original)
            with patch.object(installer.platform,'system',return_value='Windows'), \
                    patch.dict(os.environ,{'APPDATA':str(roaming),'LOCALAPPDATA':str(local)}), \
                    patch.object(sys,'argv',['install.py','--enable']):
                installer.main()
            self.assertIn('enable_linework=true',config.read_text())
            self.assertIn('enable_other=true',config.read_text())
            self.assertIn('[other]\nkeep=true',config.read_text())
            backups = list((resource/'linework-backups').iterdir())
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'kritarc').read_text(),original)
            self.assertEqual((backups[0]/'linework/old-marker').read_text(),'keep')
            self.assertTrue((previous/'native_library.py').exists())

    def test_library_selection_and_directory_lifetime(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        with patch.object(module.platform,'system',return_value='Linux'), \
                patch.object(module.platform,'machine',return_value='x86_64'):
            self.assertEqual(module.library_path('native').name,'liblinework_native.so')
        qt = types.ModuleType('PyQt5.QtCore')
        qt.QCoreApplication = types.SimpleNamespace(applicationDirPath=lambda:'C:/Krita/bin')
        handles = [object(),object()]
        with patch.object(module.platform,'system',return_value='Windows'), \
                patch.object(module.platform,'machine',return_value='AMD64'), \
                patch.dict(sys.modules,{'PyQt5.QtCore':qt}), \
                patch.object(module.os,'add_dll_directory',side_effect=handles,create=True) as add:
            self.assertEqual(module.library_path('native').name,'linework_native.dll')
            self.assertEqual(module.library_path('vectorize').name,'linework_vectorize.dll')
            self.assertEqual(add.call_count,2)
            self.assertEqual(module._DLL_DIRECTORIES,handles)

    def test_unsupported_architecture_fails_before_loading(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        with patch.object(module.platform,'machine',return_value='arm64'):
            with self.assertRaises(ValueError):module.library_path('native')


if __name__ == '__main__':
    unittest.main()
