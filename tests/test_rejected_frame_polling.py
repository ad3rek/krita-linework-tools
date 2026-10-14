# SPDX-License-Identifier: GPL-3.0-or-later
"""A rejected raster frame must not be decoded again on each GUI timer."""
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace,MethodType
import unittest
from unittest.mock import patch


class RejectedFramePollingTests(unittest.TestCase):
    def setUp(self):
        source=Path(os.environ.get('LINEWORK_TEST_SOURCE',Path(__file__).resolve().parents[1]))/'linework/tool_options.py'
        cls=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='LineworkToolOptions')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='poll')
        self.revision=7;self.annotation=b'original';self.reads=0
        self.layer=SimpleNamespace(type=lambda:'paintlayer')
        self.doc=SimpleNamespace(annotation=lambda name:self.annotation)
        view=SimpleNamespace(document=lambda:self.doc,currentBrushPreset=lambda:None,
               flakeToImageTransform=lambda:None,canvas=lambda:SimpleNamespace(wrapAroundMode=lambda:False))
        self.obj=SimpleNamespace(_selection_pending=False,_polling=False,_input_depth=0,_writing=False,_clearing=False,
                 _brush_change=False,active=True,overlay=None,_rejected_binding=None,_bound_annotation=None,
                 _unrecognized_annotation=None,layer=None,binding=None,
                 _canvas=SimpleNamespace(isVisible=lambda:True),current_view=lambda:view,
                 binding_key=lambda *args:('document','layer','frame'),brush_label=SimpleNamespace(setText=lambda value:None))
        def clear():self.obj.binding=None;self.obj._rejected_binding=None
        self.obj.clear_binding=clear;self.obj.fail=lambda exc:clear()
        def read(*args):
            self.reads+=1
            raise ValueError('Raster pixels changed outside Linework')
        busy=type('Busy',(RuntimeError,),{})
        namespace={'__package__':'linework','__name__':'linework.tool_options','native_busy':lambda:False,
                   'active_node':lambda view:self.layer,'ANNOTATION':'test','AnimationBusy':busy,
                   'read_layer':read,'tr':lambda value:value}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
        self.obj.poll=MethodType(namespace['poll'],self.obj)
        modules=patch.dict(sys.modules,{'linework.tools':SimpleNamespace(active_tool=lambda:3),
               'linework.animation':SimpleNamespace(playback=lambda view:False,pixel_revision=lambda layer:self.revision)})
        modules.start();self.addCleanup(modules.stop)

    def test_periodic_timers_decode_a_rejected_frame_only_once(self):
        for _ in range(30):self.obj.poll()
        self.assertEqual(self.reads,1)
        self.assertFalse(self.obj._polling)

    def test_native_undo_revision_and_annotation_changes_allow_rebinding(self):
        self.obj.poll();self.revision+=1;self.obj.poll()
        self.assertEqual(self.reads,2)
        self.annotation=b'new annotation';self.obj.poll()
        self.assertEqual(self.reads,3)

    def test_explicit_input_retries_verification_and_closed_view_releases_cache(self):
        self.obj.poll();self.obj.poll(allow_input=True)
        self.assertEqual(self.reads,2)
        self.obj.current_view=lambda:None;self.obj.poll()
        self.assertIsNone(self.obj._rejected_binding)


if __name__=='__main__':unittest.main()
