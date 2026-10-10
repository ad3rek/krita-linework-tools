# SPDX-License-Identifier: GPL-3.0-or-later
"""Installation paths and native library selection across supported platforms."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

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
        handles = [object(),object()]
        with patch.object(module.platform,'system',return_value='Windows'), \
                patch.object(module.platform,'machine',return_value='AMD64'), \
                patch.object(module,'application_directory',return_value='C:/Krita/bin'), \
                patch.object(module.os,'add_dll_directory',side_effect=handles,create=True) as add:
            self.assertEqual(module.library_path('native').name,'linework_native.dll')
            self.assertEqual(module.library_path('vectorize').name,'linework_vectorize.dll')
            self.assertEqual(add.call_count,2)
            self.assertEqual(module._DLL_DIRECTORIES,handles)

    def test_unsupported_architecture_fails_before_loading(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        with patch.object(module.platform,'machine',return_value='arm64'):
            with self.assertRaises(ValueError):module.library_path('native')

    def test_native_bridge_accepts_official_version_and_build_suffix(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        path = Path('C:/Krita/pykrita/linework/native/linework_native.dll')
        bridge = object()
        for version in ('5.2.14', '5.2.14 (git 31056c6)', '5.2.14-1'):
            with self.subTest(version=version), \
                    patch.object(module, 'library_path', return_value=path), \
                    patch.object(module.ctypes, 'PyDLL', return_value=bridge) as load:
                self.assertIs(module.load_native_bridge(version), bridge)
                load.assert_called_once_with(str(path))

    def test_windows_versions_select_their_own_native_bridge(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        for version, qt in [('5.3.3',5),('5.3.4',5),('5.3.4.1',5),('6.0.3',6),('6.0.4',6),('6.0.4.1',6)]:
            bridge = types.SimpleNamespace(
                linework_bridge_krita_version=Mock(return_value=version.encode()),
                linework_bridge_qt_version=Mock(return_value=(str(qt)+'.0.0').encode()))
            with self.subTest(version=version), \
                    patch.object(module.platform,'system',return_value='Windows'), \
                    patch.object(module.platform,'machine',return_value='AMD64'), \
                    patch.object(module,'application_directory',return_value='C:/Krita/bin'), \
                    patch.object(module.os,'add_dll_directory',return_value=object(),create=True), \
                    patch.object(module.ctypes,'PyDLL',return_value=bridge) as load:
                self.assertIs(module.load_native_bridge(version+' (git abc123)'),bridge)
                self.assertEqual(Path(load.call_args.args[0]).parts[-2:],(version,'linework_native.dll'))

    def test_mispackaged_version_or_qt_bridge_is_rejected(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        for compiled, qt in [('6.0.4','6.8.0'),('6.0.3','5.15.7')]:
            bridge = types.SimpleNamespace(
                linework_bridge_krita_version=Mock(return_value=compiled.encode()),
                linework_bridge_qt_version=Mock(return_value=qt.encode()))
            with self.subTest(compiled=compiled,qt=qt), \
                    patch.object(module.platform,'system',return_value='Windows'), \
                    patch.object(module,'library_path',return_value=Path('bad.dll')), \
                    patch.object(module.ctypes,'PyDLL',return_value=bridge):
                with self.assertRaises(ValueError):module.load_native_bridge('6.0.3')

    def test_incompatible_krita_never_loads_dll_and_explains_installation(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        for version in ('5.2.13', '5.2.15', '5.2.140', '5.3.5', '6.0.5', '5.2.14.1', ''):
            with self.subTest(version=version), \
                    patch.object(module.platform, 'system', return_value='Windows'), \
                    patch.object(module, 'library_path') as resolve, \
                    patch.object(module.ctypes, 'PyDLL') as load:
                with self.assertRaises(ValueError) as error:
                    module.load_native_bridge(version)
                resolve.assert_not_called()
                load.assert_not_called()
                message = str(error.exception)
                self.assertIn('Detected: Krita '+(version or '(unknown)'), message)
                self.assertIn('Supported on Windows: Krita 5.2.14, 5.3.3, 5.3.4, 5.3.4.1, 6.0.3, 6.0.4, 6.0.4.1', message)
                self.assertIn('Windows x86_64 Linework package', message)
                self.assertIn(module.KRITA_DOWNLOAD, message)

    def test_native_loader_error_preserves_path_version_and_cause(self):
        module = standalone('native_paths', ROOT/'linework/native_library.py')
        path = Path('C:/Krita/pykrita/linework/native/linework_native.dll')
        cause = OSError('WinError 126: The specified module could not be found')
        with patch.object(module, 'library_path', return_value=path), \
                patch.object(module.ctypes, 'PyDLL', side_effect=cause):
            with self.assertRaises(ValueError) as error:
                module.load_native_bridge('5.2.14 (git 31056c6)')
            self.assertIs(error.exception.__cause__, cause)
            self.assertIn(str(path), str(error.exception))
            self.assertIn('5.2.14 (git 31056c6)', str(error.exception))
            self.assertIn('WinError 126', str(error.exception))


if __name__ == '__main__':
    unittest.main()
