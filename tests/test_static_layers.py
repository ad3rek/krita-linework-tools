# SPDX-License-Identifier: GPL-3.0-or-later
"""Static conversion must preserve the source and reject ambiguous frames."""
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
class StaticLayerTests(unittest.TestCase):
 def setUp(self):
  source=ROOT/'linework/static_layers.py'
  fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='static_copy')
  self.source=SimpleNamespace(type=lambda:'paintlayer',name=lambda:'Drawing')
  self.removed=[];self.names=[];self.created=[];self.writes=[]
  self.layer=SimpleNamespace(remove=lambda:self.removed.append(True),setName=self.names.append)
  self.info={'animated':True,'frames':[{'time':0}]};self.payload={'strokes':[{'id':'original'}]}
  self.env={'tr':lambda text:text,'bootstrap_layer':lambda *args:self.info,
            'record':lambda *args:self.payload,'load_strokes':lambda data:copy.deepcopy(data),
            'SavedFrameRenderer':lambda payload:payload,'write_layer':lambda *args:self.writes.append(args)}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),self.env)
  self.copy=self.env['static_copy']
 def create(self,*args):self.created.append(args);return self.layer
 def test_conversion_retains_source_and_saved_appearances(self):
  original=copy.deepcopy(self.payload)
  self.assertIs(self.copy('document',self.source,self.create),self.layer)
  self.assertEqual(self.created,[('document','vectorlayer')])
  self.assertEqual(self.writes[0][2],original['strokes'])
  self.assertIs(self.writes[0][3],self.payload)
  self.assertEqual(self.payload,original);self.assertFalse(self.removed)
 def test_animation_with_several_frames_is_refused_before_creation(self):
  self.info['frames'].append({'time':8})
  with self.assertRaises(ValueError):self.copy('doc',self.source,self.create)
  self.assertFalse(self.created)
 def test_ordinary_paint_layer_is_refused_before_creation(self):
  self.info['animated']=False
  with self.assertRaises(ValueError):self.copy('doc',self.source,self.create)
  self.assertFalse(self.created)
 def test_changed_raster_pixels_do_not_create_a_misleading_copy(self):
  def reject(*args):raise ValueError('Raster fingerprint changed')
  self.env['record']=reject
  with self.assertRaises(ValueError):self.copy('doc',self.source,self.create)
  self.assertFalse(self.created)
 def test_failed_import_removes_only_the_new_destination(self):
  def reject(*args):raise RuntimeError('Import failed')
  self.env['write_layer']=reject
  with self.assertRaises(RuntimeError):self.copy('doc',self.source,self.create)
  self.assertEqual(self.removed,[True])
  self.assertEqual(self.payload['strokes'],[{'id':'original'}])
if __name__=='__main__':unittest.main()
