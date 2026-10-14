# SPDX-License-Identifier: GPL-3.0-or-later
"""A parent-layer transform can change world coordinates without changing SVG."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PyQt5.QtGui import QTransform


ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('affine_test_model',ROOT/'linework/model.py')
model=importlib.util.module_from_spec(spec);sys.modules[spec.name]=model;spec.loader.exec_module(model)


class NativeAffineSyncTests(unittest.TestCase):
    def setUp(self):
        source=Path(os.environ.get('LINEWORK_TEST_SOURCE',ROOT))/'linework/transforms.py'
        fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='sync_layer')
        self.stroke=model.Stroke([model.Point(10,20),model.Point(40,60)],kind='line',width=10)
        name='lw_'+self.stroke.uid
        self.shape=SimpleNamespace(name=lambda:name)
        self.layer=SimpleNamespace(type=lambda:'vectorlayer',shapes=lambda:[self.shape],locked=lambda:False)
        self.record={'strokes':[self.stroke.data()], 'shapes':{name:'same SVG'},'geometry':[100,100,72,72],
                     'poses':{name:{'frame':[1,0,0,1,0,0],'payload':'same appearance','payload_version':2}}}
        self.data={'version':8,'layers':{'vector':copy.deepcopy(self.record),
                     'animation':{'kind':'animated','frames':{'0':{'encoding':'shared-brushes-v1'}}}}}
        self.current=QTransform.fromTranslate(30,40)
        self.writes=[];self.protected=[]
        self.doc=SimpleNamespace(xRes=lambda:72,yRes=lambda:72,
             setAnnotation=lambda *args:self.writes.append(json.loads(bytes(args[-1]))),setModified=lambda value:None,
             refreshProjection=lambda:(_ for _ in ()).throw(AssertionError('Do not repaint an adopted native transform')),
             waitForDone=lambda:None)
        def coefficients(m):return [m.m11(),m.m12(),m.m21(),m.m22(),m.dx(),m.dy()]
        namespace={'__package__':'linework','__name__':'linework.transforms','QTransform':QTransform,'QByteArray':bytes,
                   'json':json,'math':__import__('math'),'load_strokes':model.load_strokes,
                   'transform_stroke':model.transform_stroke,'shape_frame':lambda shape:self.current,
                   'vector_layer':lambda layer:layer,'coefficients':coefficients,
                   'canonical_digest':lambda *args:'same appearance','legacy_states':lambda *args:{},
                   'shape_state':lambda shape:{'frame':coefficients(self.current),'payload':'same appearance','payload_version':2},
                   'tr':lambda text:text,
                   'NativeBrushRenderer':lambda *args:(_ for _ in ()).throw(AssertionError('Native pixels already transformed'))}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),namespace)
        self.namespace=namespace;self.sync=namespace['sync_layer']
        modules=patch.dict(sys.modules,{'linework.storage':SimpleNamespace(metadata=lambda doc:copy.deepcopy(self.data),
                    layer_id=lambda layer:'vector',digest=lambda shape:'same SVG',check_geometry=lambda *args:None,ANNOTATION='test'),
                  'linework.animation':SimpleNamespace(protect_save=lambda *args:self.protected.append(args))})
        modules.start();self.addCleanup(modules.stop)

    def test_parent_translation_updates_points_even_when_svg_digest_is_unchanged(self):
        self.assertTrue(self.sync(self.doc,self.layer,None))
        points=self.writes[-1]['layers']['vector']['strokes'][0]['points']
        self.assertEqual([point[:2] for point in points],[[40.0,60.0],[70.0,100.0]])

    def test_nonuniform_scale_updates_handles_and_width_without_repainting(self):
        self.current=QTransform.fromScale(2,3)
        self.assertTrue(self.sync(self.doc,self.layer,None))
        stroke=self.writes[-1]['layers']['vector']['strokes'][0]
        self.assertEqual([p[:2] for p in stroke['points']],[[20.0,60.0],[80.0,180.0]])
        self.assertAlmostEqual(stroke['width'],10*(6**.5))

    def test_animation_schema_and_saved_frames_are_preserved(self):
        self.sync(self.doc,self.layer,None)
        self.assertEqual(self.writes[-1]['version'],8)
        self.assertEqual(self.writes[-1]['layers']['animation'],self.data['layers']['animation'])
        self.assertEqual(len(self.protected),1)

    def test_external_appearance_changes_are_rejected_without_annotation_write(self):
        self.namespace['canonical_digest']=lambda *args:'changed appearance'
        with self.assertRaises(ValueError):self.sync(self.doc,self.layer,None)
        self.assertFalse(self.writes)


if __name__=='__main__':unittest.main()
