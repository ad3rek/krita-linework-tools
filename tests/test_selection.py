"""Stable identities, mixed point/curve targets and native shape inheritance."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
spec = importlib.util.spec_from_file_location('selection', Path(__file__).resolve().parents[1]/'linework/selection.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
Selection = module.Selection
STROKES = [SimpleNamespace(uid='a', points=[0, 1, 2]), SimpleNamespace(uid='b', points=[0, 1])]

class SelectionTests(unittest.TestCase):
    def test_native_shapes_target_all_anchors(self):
        s=Selection();s.set_strokes(['a','b']);s.prune(STROKES)
        self.assertEqual(s.point_keys(STROKES),{('a',0),('a',1),('a',2),('b',0),('b',1)})
    def test_shift_point_can_remove_one_anchor_from_inherited_shape(self):
        s=Selection();s.set_strokes(['a','b']);s.toggle_point('a',1,STROKES)
        self.assertNotIn(('a',1),s.point_keys(STROKES));self.assertEqual(s.ids(),{'a','b'})
        s.toggle_point('a',1,STROKES);self.assertEqual(len(s.point_keys(STROKES)),5)
    def test_points_from_different_curves_do_not_target_unselected_anchors(self):
        s=Selection();s.set_points([('a',1),('b',0)])
        self.assertEqual(s.ids(),{'a','b'});self.assertEqual(s.point_keys(STROKES),{('a',1),('b',0)})
    def test_removed_shape_or_point_is_pruned_after_history(self):
        s=Selection();s.set_points([('a',2),('b',1)]);s.prune([SimpleNamespace(uid='a',points=[0,1])])
        self.assertFalse(s.ids());self.assertEqual(s.primary,(None,-1))
    def test_toggle_curve_removes_all_its_selected_points(self):
        s=Selection();s.set_points([('a',0),('a',2),('b',1)]);s.toggle_stroke('a')
        self.assertEqual(s.point_keys(STROKES),{('b',1)})

if __name__=='__main__':unittest.main()
