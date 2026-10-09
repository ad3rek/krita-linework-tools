# SPDX-License-Identifier: GPL-3.0-or-later
import importlib, math, random, sys, types, unittest
from pathlib import Path
pkg=types.ModuleType('spatial_test');pkg.__path__=[str(Path(__file__).resolve().parents[1]/'linework')];sys.modules[pkg.__name__]=pkg
m=importlib.import_module(pkg.__name__+'.model');s=importlib.import_module(pkg.__name__+'.spatial');e=importlib.import_module(pkg.__name__+'.eraser')
class SpatialTests(unittest.TestCase):
 def test_grid_negative_boundaries_and_huge_query(self):
  g=s.Grid(64,4)
  for i,box in enumerate([(-64,-64,-64,-64),(0,0,0,0),(-1000,-1000,1000,1000),(63,64,66,65)]):g.insert(i,box)
  for box in [(-64,-64,-64,-64),(64,64,64,64),(-1e12,-1e12,1e12,1e12),(2000,2000,2100,2100)]:
   self.assertEqual(g.query(box),{i for i,b in g.bounds.items() if s.intersects(b,box)})
  g.remove(2);g.remove(2);self.assertNotIn(2,g.query((-1e12,-1e12,1e12,1e12)))
 def test_updating_entry_removes_old_cells(self):
  g=s.Grid();g.insert('a',(0,0,1,1));g.insert('a',(500,500,501,501))
  self.assertFalse(g.query((0,0,1,1)));self.assertEqual(g.query((500,500,501,501)),{'a'})
 def test_anchor_candidates_match_brute_force(self):
  rng=random.Random(31)
  strokes=[m.Stroke([m.Point(rng.uniform(-400,400),rng.uniform(-400,400)) for _ in range(12)]) for _ in range(70)]
  index=s.SpatialIndex(strokes)
  for _ in range(150):
   x,y=rng.uniform(-400,400),rng.uniform(-400,400);box=(x-25,y-25,x+25,y+25)
   expected={(stroke.uid,i) for stroke in strokes for i,p in enumerate(stroke.points) if box[0]<=p.x<=box[2] and box[1]<=p.y<=box[3]}
   self.assertEqual(index.anchors_in(box),expected)
 def test_controls_and_outline_contained_even_with_scalar_overshoot(self):
  strokes=[m.Stroke([m.Point(0,0,.1,handle_out=(0,900),thickness=.2,thickness_out=-30),m.Point(100,0,.2,handle_in=(-800,-400),thickness=.7,thickness_in=22)],width=55,minimum=.2),m.Stroke([m.Point(0,0),m.Point(80,900),m.Point(-30,0)],width=130),m.Stroke([m.Point(-100,-100)],width=2000)]
  for stroke in strokes:
   box=s.stroke_bounds(stroke)
   for x,y in m.outline(stroke):self.assertTrue(box[0]-1e-8<=x<=box[2]+1e-8 and box[1]-1e-8<=y<=box[3]+1e-8,(box,x,y))
   for point in m.samples(stroke):self.assertTrue(box[0]<=point.x<=box[2] and box[1]<=point.y<=box[3])
 def test_swept_eraser_candidates_do_not_miss_curves(self):
  rng=random.Random(72)
  strokes=[m.Stroke([m.Point(rng.uniform(-200,200),rng.uniform(-200,200)) for _ in range(4)],width=rng.uniform(1,20)) for _ in range(50)]
  index=s.SpatialIndex(strokes)
  for _ in range(60):
   a,b=m.Point(rng.uniform(-240,240),rng.uniform(-240,240)),m.Point(rng.uniform(-240,240),rng.uniform(-240,240));radius=8
   box=(min(a.x,b.x)-radius,min(a.y,b.y)-radius,max(a.x,b.x)+radius,max(a.y,b.y)+radius)
   expected={stroke.uid for stroke in strokes if e.hit_center(m.samples(stroke),a,b,radius)}
   self.assertTrue(expected<=index.strokes_in(box))
 def test_sparse_point_eraser_matches_all_anchor_weights(self):
  rng=random.Random(63);strokes=[m.Stroke([m.Point(rng.uniform(-200,200),rng.uniform(-200,200)) for _ in range(10)]) for _ in range(30)];index=s.SpatialIndex(strokes)
  for _ in range(50):
   a,b=m.Point(rng.uniform(-200,200),rng.uniform(-200,200)),m.Point(rng.uniform(-200,200),rng.uniform(-200,200));r=12
   box=(min(a.x,b.x)-r,min(a.y,b.y)-r,max(a.x,b.x)+r,max(a.y,b.y)+r)
   groups={}
   for uid,i in index.anchors_in(box):groups.setdefault(uid,[]).append(i)
   actual={uid:e.point_weights(index.strokes[uid],a,b,r,.65,indices) for uid,indices in groups.items()}
   expected={stroke.uid:e.point_weights(stroke,a,b,r,.65) for stroke in strokes}
   self.assertEqual({u:w for u,w in actual.items() if w},{u:w for u,w in expected.items() if w})
 def test_removing_path_keeps_other_candidates_and_can_rebuild(self):
  a,b=m.Stroke([m.Point(0,0)]),m.Stroke([m.Point(100,100)])
  index=s.SpatialIndex([a,b]);index.remove(a.uid)
  self.assertNotIn(a.uid,index.strokes_in((-1000,-1000,1000,1000)));self.assertEqual(index.anchors_in((-1,-1,1,1)),set())
  self.assertEqual(s.SpatialIndex([a,b]).anchors_in((-1,-1,1,1)),{(a.uid,0)})
 def test_empty_index(self):
  index=s.SpatialIndex([]);self.assertFalse(index.anchors_in((0,0,100,100)));self.assertFalse(index.strokes_in((0,0,100,100)))
 def test_incremental_geometry_update_and_replaced_stroke(self):
  a,b=m.Stroke([m.Point(0,0),m.Point(10,10)]),m.Stroke([m.Point(100,100)])
  index=s.SpatialIndex([a,b]);a.points.pop();a.points[0].x=600;index.update(a)
  self.assertEqual(index.anchors_in((-1,-1,11,11)),set());self.assertEqual(index.anchors_in((599,-1,601,1)),{(a.uid,0)})
  replacement=m.Stroke([m.Point(-300,-300)],uid=a.uid);index.update(replacement)
  self.assertIs(index.strokes[a.uid],replacement);self.assertEqual(index.anchors_in((599,-1,601,1)),set())
  self.assertEqual(index.anchors_in((99,99,101,101)),{(b.uid,0)})
if __name__=='__main__':unittest.main()
