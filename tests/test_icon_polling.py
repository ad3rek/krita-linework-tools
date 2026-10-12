# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise icon polling against a large real Qt hierarchy without Krita."""
import ast
import ctypes
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PyQt5 import sip
    from PyQt5.QtCore import QCoreApplication, QEvent
    from PyQt5.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
    from PyQt5.QtWidgets import (QAbstractButton, QAbstractItemView, QAction,
                                QApplication, QLabel, QToolButton, QTreeView, QWidget)
except ImportError:
    QApplication = None


def load_function(path, name, namespace):
    node = next(node for node in ast.parse(path.read_text()).body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


@unittest.skipIf(QApplication is None, 'PyQt5 is required for real Qt icon polling tests')
class IconPollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'linework'
        tree = ast.parse((root / 'tools.py').read_text())
        constants = {node.targets[0].id: ast.literal_eval(node.value)
                     for node in tree.body if isinstance(node, ast.Assign)
                     and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id in ('TOOL_IDS', 'TOOL_LABELS')}
        self.ids = constants['TOOL_IDS']
        self.tools = dict(constants, sip=sip, tr=lambda text: text, _icons={},
                          QAction=QAction, QAbstractButton=QAbstractButton,
                          QIcon=QIcon, QPixmap=QPixmap, QPainter=QPainter,
                          QPalette=QPalette, QColor=QColor, Path=Path,
                          __file__=str(root / 'tools.py'))
        self.theme = load_function(root / 'tools.py', 'theme_icons', self.tools)
        self.native_calls = []
        calls = self.native_calls

        class Update:
            def __call__(self, pointer, layers, icon):
                calls.append((pointer, layers))
                return 1

        library = SimpleNamespace(linework_layer_icons=Update())
        self.native = dict(sip=sip, ctypes=ctypes, Path=Path,
                           __file__=str(root / 'native_brush.py'), __package__='linework',
                           _BRIDGE_LIBRARY=library, load_library=lambda: library)
        self.layer_icons = load_function(root / 'native_brush.py', 'update_layer_icons', self.native)
        self.qt = patch.dict(sys.modules, {'linework.qt': SimpleNamespace(QAbstractItemView=QAbstractItemView)})
        self.qt.start()
        self.addCleanup(self.qt.stop)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            if not sip.isdeleted(window):
                window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def make_window(self, clutter=0):
        class Window(QWidget):
            def __init__(self):
                super().__init__()
                self.lookups = 0

            def findChild(self, *args):
                self.lookups += 1
                return super().findChild(*args)

            def findChildren(self, *args):
                self.lookups += 1
                return super().findChildren(*args)

        class NodeView(QTreeView):
            pass

        window = Window()
        self.windows.append(window)
        window.clutter = [QLabel('preset', window) for _ in range(clutter)]
        window.actions, window.buttons = [], []
        for ident in self.ids:
            action = QAction(window)
            action.setObjectName(ident)
            window.actions.append(action)
            button = QToolButton(window)
            button.setObjectName(ident)
            window.buttons.append(button)
        window.layer_view = NodeView(window)
        window.layer_view.setObjectName('listLayers')
        return window

    def poll(self, window, layers=()):
        self.theme(window)
        self.layer_icons(window, layers)

    def test_repeated_polling_does_not_scan_thousands_of_preset_widgets(self):
        window = self.make_window(5000)
        self.poll(window)
        lookups = window.lookups
        for _ in range(30):
            self.poll(window, ('layer-id',))
        self.assertEqual(window.lookups, lookups)
        self.assertEqual(self.native_calls[-1], (sip.unwrapinstance(window.layer_view), b'layer-id'))
        self.assertTrue(all(not button.icon().isNull() for button in window.buttons))

    def test_theme_changes_refresh_icons_without_rescanning(self):
        window = self.make_window()
        self.poll(window)
        before = window.buttons[0].icon().cacheKey()
        lookups = window.lookups
        palette = window.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor('#123456'))
        window.setPalette(palette)
        self.poll(window)
        self.assertNotEqual(window.buttons[0].icon().cacheKey(), before)
        self.assertEqual(window.lookups, lookups)

    def test_rebuilt_controls_and_layer_docker_are_found_after_deletion(self):
        window = self.make_window()
        self.poll(window)
        window.buttons[0].deleteLater()
        old_view = window.layer_view
        old_view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        button = QToolButton(window)
        button.setObjectName(self.ids[0])
        view = type(old_view)(window)
        view.setObjectName('listLayers')
        self.poll(window)
        self.assertFalse(button.icon().isNull())
        self.assertEqual(self.native_calls[-1][0], sip.unwrapinstance(view))

    def test_each_window_keeps_its_own_controls_and_layer_model(self):
        first, second = self.make_window(), self.make_window()
        self.poll(first, ('first',))
        self.poll(second, ('second',))
        self.assertEqual(self.native_calls[-2:], [
            (sip.unwrapinstance(first.layer_view), b'first'),
            (sip.unwrapinstance(second.layer_view), b'second')])
        lookups = (first.lookups, second.lookups)
        self.poll(first)
        self.poll(second)
        self.assertEqual((first.lookups, second.lookups), lookups)

    def test_closing_a_window_releases_retained_wrappers(self):
        window = self.make_window()
        self.poll(window)
        pointer = sip.unwrapinstance(window)
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertNotIn(pointer, self.tools['_icon_window_cache'])
        self.assertNotIn(pointer, self.native['_icon_window_cache'])


if __name__ == '__main__':
    unittest.main()
