# SPDX-License-Identifier: GPL-3.0-or-later
"""Polling must not pump synchronized GUI events or reenter itself."""
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace, MethodType
import unittest
from unittest.mock import patch


class TransformPollingTests(unittest.TestCase):
    def setUp(self):
        root=Path(os.environ.get('LINEWORK_TEST_SOURCE',Path(__file__).resolve().parents[1]))
        source=root/'linework/plugin.py'
        cls=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef))
        self.doc=SimpleNamespace(activeNode=lambda: (_ for _ in ()).throw(AssertionError('activeNode pumps GUI events')))
        self.view=SimpleNamespace(document=lambda:self.doc)
        self.window=SimpleNamespace(activeView=lambda:self.view)
        application=SimpleNamespace(activeWindow=lambda:self.window,windows=lambda:[],documents=lambda:[])
        self.calls={'busy':0,'flush':0,'sync':0}
        self.obj=SimpleNamespace(_syncing=False,_tablet_down=False,_transform_pending=None,_updating_icons=False,
                                 _shutting_down=False,_annotations={})
        self.obj.clipboard=SimpleNamespace(watch_current_actions=lambda:None)
        def busy():
            self.calls['busy']+=1
            if self.calls['busy']==1:self.obj.update_icons()
            return False
        namespace={'__package__':'linework','__name__':'linework.plugin',
                   'Krita':SimpleNamespace(instance=lambda:application),'native_busy':busy,
                   'active_node':lambda view:SimpleNamespace(type=lambda:'paintlayer'),
                   'QApplication':SimpleNamespace(mouseButtons=lambda:0,activeModalWidget=lambda:None),
                   'Qt':SimpleNamespace(MouseButton=SimpleNamespace(NoButton=0))}
        for method in cls.body:
            if isinstance(method,ast.FunctionDef) and method.name in ('sync_native_transforms','update_icons','_update_icons'):
                exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
                setattr(self.obj,method.name,MethodType(namespace[method.name],self.obj))
        self.modules=patch.dict(sys.modules,{
            'linework.tools':SimpleNamespace(active_tool=lambda:-1),
            'linework.transforms':SimpleNamespace(pending_signature=lambda *a:None,sync_layer=lambda *a:False),
            'linework.animation':SimpleNamespace(flush=lambda:self.calls.__setitem__('flush',self.calls['flush']+1))})
        self.modules.start();self.addCleanup(self.modules.stop)

    def test_native_transform_poll_reads_selection_without_delivering_gui_events(self):
        self.obj.sync_native_transforms()
        self.assertIsNone(self.obj._transform_pending)

    def test_nested_timer_does_not_repeat_frame_sync(self):
        self.obj.sync_native_transforms=lambda:self.calls.__setitem__('sync',self.calls['sync']+1)
        self.obj.update_icons()
        self.assertEqual(self.calls,{'busy':1,'flush':1,'sync':1})
        self.assertFalse(self.obj._updating_icons)

    def test_guard_is_released_when_native_call_fails(self):
        self.obj.sync_native_transforms=lambda:(_ for _ in ()).throw(ValueError('transient native failure'))
        with self.assertRaises(ValueError):self.obj.update_icons()
        self.assertFalse(self.obj._updating_icons)
        self.obj.sync_native_transforms=lambda:None
        self.obj.update_icons()
        self.assertFalse(self.obj._updating_icons)


if __name__=='__main__':unittest.main()
