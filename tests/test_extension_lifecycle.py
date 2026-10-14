# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep retries bounded and release annotation data when documents close."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace, MethodType
import sys
import unittest
from unittest.mock import patch


class Busy(RuntimeError):
    pass


class ExtensionLifecycleTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get('LINEWORK_TEST_SOURCE', Path(__file__).resolve().parents[1]))
        path = root/'linework/plugin.py'
        cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef))
        self.documents = [self.document('first'), self.document('second')]
        app = SimpleNamespace(documents=lambda:self.documents, windows=lambda:[])
        self.callbacks = []
        self.calls = []
        self.obj = SimpleNamespace(_initializing_animation=False, _animation_init_queued=False,
                                   _shutting_down=False, _annotations={'first':(b'large',()), 'closed':(b'large',())},
                                   clipboard=SimpleNamespace(watch_current_actions=lambda:None),
                                   sync_native_transforms=lambda:None)
        namespace = {'__name__':'linework.plugin', '__package__':'linework',
                     'Krita':SimpleNamespace(instance=lambda:app), 'native_busy':lambda:False,
                     'QTimer':SimpleNamespace(singleShot=lambda ms,fn:self.callbacks.append((ms,fn)))}
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name in (
                    'initialize_animation', 'retry_animation_initialization', '_update_icons'):
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
                setattr(self.obj, node.name, MethodType(namespace[node.name], self.obj))
        self.bootstrap = lambda doc:self.calls.append(doc)
        modules = patch.dict(sys.modules, {'linework.animation':SimpleNamespace(
            bootstrap_document=lambda doc:self.bootstrap(doc), AnimationBusy=Busy, flush=lambda:None)})
        modules.start();self.addCleanup(modules.stop)

    @staticmethod
    def document(name):
        return SimpleNamespace(rootNode=lambda:SimpleNamespace(uniqueId=lambda:SimpleNamespace(toString=lambda:name)))

    def test_two_busy_documents_share_one_retry(self):
        self.bootstrap = lambda doc:(_ for _ in ()).throw(Busy())
        self.obj.initialize_animation()
        self.assertEqual(len(self.callbacks), 1)

    def test_repeated_notifications_do_not_accumulate_retries(self):
        self.bootstrap = lambda doc:(_ for _ in ()).throw(Busy())
        for _ in range(20):self.obj.initialize_animation()
        self.assertEqual(len(self.callbacks), 1)
        self.bootstrap = lambda doc:self.calls.append(doc)
        self.callbacks[0][1]()
        self.assertEqual(self.calls, self.documents)
        self.assertFalse(self.obj._animation_init_queued)

    def test_native_event_delivery_does_not_reenter_initialization(self):
        def bootstrap(doc):
            self.calls.append(doc)
            if len(self.calls)==1:self.obj.initialize_animation()
        self.bootstrap = bootstrap
        self.obj.initialize_animation()
        self.assertEqual(self.calls, self.documents)
        self.assertFalse(self.obj._initializing_animation)

    def test_shutdown_does_not_touch_documents_or_schedule_retries(self):
        self.obj._shutting_down = True
        self.bootstrap = lambda doc:(_ for _ in ()).throw(Busy())
        self.obj.initialize_animation()
        self.assertFalse(self.callbacks)

    def test_closed_annotations_are_released_but_inactive_open_documents_remain_cached(self):
        self.obj._update_icons()
        self.assertEqual(self.obj._annotations, {'first':(b'large',())})


if __name__=='__main__':unittest.main()
