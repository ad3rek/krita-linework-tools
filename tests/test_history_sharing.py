# SPDX-License-Identifier: GPL-3.0-or-later
import copy,importlib.util,sys,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('history_sharing_model',Path(__file__).resolve().parents[1]/'linework/model.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class HistorySharingTests(unittest.TestCase):
 def setUp(self):
  self.strokes=[m.Stroke([m.Point(i*100,0),m.Point(i*100+50,30)],brush={'name':'x','nested':{'value':[1]}}) for i in range(4)]
  self.h=m.History(self.strokes,limit=3)
 def test_only_modified_snapshot_is_copied(self):
  original=list(self.h.current);self.strokes[1].points[0].x+=8;self.h.commit(self.strokes)
  self.assertIsNot(self.h.current[1],original[1])
  for i in (0,2,3):self.assertIs(self.h.current[i],original[i])
  self.strokes[1].points[0].x+=8;self.strokes[1].brush['nested']['value'][0]=99
  self.assertNotEqual(self.strokes[1].data(),self.h.current[1].data())
 def test_undo_redo_results_cannot_mutate_snapshots(self):
  initial=[s.data() for s in self.strokes];self.strokes[0].points[0].x+=10;self.h.commit(self.strokes)
  changed=[s.data() for s in self.strokes]
  restored=self.h.undo();self.assertEqual([s.data() for s in restored],initial)
  restored[2].points[0].x=999;restored[2].brush['nested']['value'][0]=999
  self.assertEqual([s.data() for s in self.h.redo()],changed)
  self.assertEqual([s.data() for s in self.h.undo()],initial)
 def test_deletion_reordering_and_new_strokes_roundtrip(self):
  initial=[s.data() for s in self.strokes];updated=[self.strokes[3],self.strokes[0],m.Stroke([m.Point(0,0)])]
  self.h.commit(updated);self.assertEqual([s.data() for s in self.h.undo()],initial)
  self.assertEqual([s.data() for s in self.h.redo()],[s.data() for s in updated])
 def test_limit_noop_and_branch_after_undo(self):
  self.h.commit(self.strokes);self.assertFalse(self.h.undo_stack)
  for _ in range(7):self.strokes[0].width+=1;self.h.commit(self.strokes)
  self.assertEqual(len(self.h.undo_stack),3)
  restored=self.h.undo();restored[1].color='#aabbcc';self.h.commit(restored)
  self.assertFalse(self.h.redo_stack);self.assertEqual(self.h.current[1].color,'#aabbcc')
if __name__=='__main__':unittest.main()
