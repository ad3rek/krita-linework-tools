# SPDX-License-Identifier: GPL-3.0-or-later
"""A plugin must never load Qt 5 into a Qt 6 Krita process, or vice versa."""
import importlib.util
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class BindingTests(unittest.TestCase):
    def test_use_only_the_application_binding_when_both_are_installed(self):
        for version, major in [('5.2.14',5),('5.3.3 (git abc123)',5),('5.3.4',5),
                               ('6.0.3 (git abc123)',6),('6.0.4',6)]:
            with self.subTest(version=version):
                qt = {name: SimpleNamespace() for name in ('sip','QtCore','QtGui','QtWidgets')}
                qt['QtGui'].QImage = object()
                krita = SimpleNamespace(Krita=SimpleNamespace(instance=lambda:SimpleNamespace(version=lambda:version)))
                def load(name):
                    self.assertTrue(name.startswith('PyQt'+str(major)+'.'),name)
                    return qt[name.split('.')[1]]
                with patch.dict(sys.modules,{'krita':krita}), patch('importlib.import_module',side_effect=load) as imports:
                    path = Path(__file__).resolve().parents[1]/'linework/qt.py'
                    spec = importlib.util.spec_from_file_location('test_binding',path)
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    self.assertEqual(module.QT_MAJOR,major)
                    self.assertIs(module.QImage,qt['QtGui'].QImage)
                    self.assertEqual(imports.call_count,4)


    def test_qt6_queued_input_uses_native_clone_without_timestamp_setter(self):
        path=Path(__file__).resolve().parents[1]/'linework/tool_options.py'
        tree=ast.parse(path.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LineworkToolOptions')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='copy_input')
        node.body=[n for n in node.body if not isinstance(n,ast.ImportFrom)]
        namespace={'QT_MAJOR':6}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
        class Event:
            # PyQt 6 exposes timestamp(), but deliberately has no setter.
            def __init__(self):self.pressure=.7;self.position=(20,30);self.time=12857
            def timestamp(self):return self.time
            def clone(self):return copy.deepcopy(self)
        event=Event();cloned=namespace['copy_input'](None,event)
        self.assertIsNot(cloned,event)
        self.assertEqual(cloned.timestamp(),event.timestamp())
        self.assertEqual(cloned.pressure,event.pressure)
        self.assertEqual(cloned.position,event.position)
        event.pressure=0
        self.assertEqual(cloned.pressure,.7)


if __name__ == '__main__': unittest.main()
