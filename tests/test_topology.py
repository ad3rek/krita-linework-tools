# SPDX-License-Identifier: GPL-3.0-or-later
"""Topology and eraser geometry regressions without Qt or a running Krita."""
import copy
import importlib
import math
from pathlib import Path
import sys
import types
import unittest

package = types.ModuleType('linework_topology_test')
package.__path__ = [str(Path(__file__).resolve().parents[1]/'linework')]
sys.modules[package.__name__] = package
m = importlib.import_module(package.__name__+'.model')
t = importlib.import_module(package.__name__+'.topology')
e = importlib.import_module(package.__name__+'.eraser')
Point, Stroke = m.Point, m.Stroke


def curve(offset=0, **kwargs):
    return Stroke([Point(offset,0,.2),Point(offset+40,60,.8),Point(offset+90,20,.6)], **kwargs)


class TopologyTests(unittest.TestCase):
    def assert_same(self, a, b, multiplier=1):
        self.assertLess(m.distance(a,b),1e-8)
        self.assertAlmostEqual(a.pressure,b.pressure)
        self.assertAlmostEqual(m.thickness_factor(a)*multiplier,m.thickness_factor(b))

    def test_reverse_preserves_geometry_pressure_and_width_controls(self):
        original = curve(width=20,minimum=.2,taper_start=.3,taper_end=.7)
        m.freeze_thickness(original)
        before = copy.deepcopy(original.data())
        reverse = t.reversed_stroke(original)
        self.assertEqual(original.data(),before)
        self.assertEqual((reverse.taper_start,reverse.taper_end),(.7,.3))
        for i in range(2):
            for u in (0,.13,.5,.9,1):
                a=m.segment_point(original,i,u);b=m.segment_point(reverse,1-i,1-u)
                self.assertLess(m.distance(a,b),1e-8);self.assertAlmostEqual(a.pressure,b.pressure)
                self.assertAlmostEqual(b.thickness,.2+.8*a.thickness)

    def test_join_all_endpoint_orientations_retains_both_curves_and_active_style(self):
        for ai in (0,2):
            for bi in (0,2):
                a,b=curve(width=12,color='#ee0011'),curve(200,width=36,color='#0000ee')
                m.freeze_thickness(a);m.freeze_thickness(b)
                before=[a.data(),b.data()]
                result,selected=t.join_strokes(a,ai,b,bi)
                self.assertEqual(result.uid,a.uid);self.assertEqual(result.color,a.color)
                self.assertEqual(selected,[2,3]);self.assertEqual(len(result.points),6)
                left=t.reversed_stroke(a) if ai==0 else t.prepared(a)
                right=t.reversed_stroke(b) if bi==2 else t.prepared(b)
                for source,offset,factor in ((left,0,1),(right,3,3)):
                    for i in range(2):
                        for u in (0,.2,.6,1):
                            self.assert_same(m.segment_point(source,i,u),m.segment_point(result,offset+i,u),factor)
                self.assertEqual([a.data(),b.data()],before)

    def test_line_to_curve_join_keeps_linear_segments_and_scalar_channels(self):
        a=Stroke([Point(0,0,.3),Point(100,0,.9)],width=10,kind='line')
        b=curve(200,width=30)
        result,_=t.join_strokes(a,1,b,0)
        for u in (0,.2,.8,1):self.assert_same(m.segment_point(a,0,u),m.segment_point(result,0,u))
        self.assertEqual(result.kind,'curve')

    def test_connector_is_straight_and_preserves_both_endpoint_diameters(self):
        a,b=curve(width=10),curve(200,width=25)
        result,_=t.join_strokes(a,2,b,0)
        self.assertAlmostEqual(result.width*result.points[2].thickness,6)
        self.assertAlmostEqual(result.width*result.points[3].thickness,5)
        p=m.segment_point(result,2,.5)
        self.assertAlmostEqual(p.x,(a.points[-1].x+b.points[0].x)/2)
        self.assertAlmostEqual(p.y,(a.points[-1].y+b.points[0].y)/2)

    def test_merge_consecutive_at_center_or_active_preserves_other_segments(self):
        source=Stroke([Point(i*20,10*i,.2+i*.1) for i in range(6)],width=20)
        for mode in ('center','active'):
            result,index=t.merge_points(source,[2,3],3,mode)
            self.assertEqual((index,len(result.points)),(2,5))
            self.assertEqual(result.points[2].x,50 if mode=='center' else 60)
            self.assertAlmostEqual(result.points[2].thickness,.45 if mode=='center' else .5)
            for old,new in ((0,0),(4,3)):
                for u in (0,.4,.8,1):self.assert_same(m.segment_point(source,old,u),m.segment_point(result,new,u))

    def test_weld_two_endpoints_uses_active_position_or_average(self):
        a,b=curve(width=10),curve(200,width=30)
        for mode in ('center','active'):
            result,selected=t.join_strokes(a,2,b,0,weld=True,position=mode)
            self.assertEqual(selected,[2]);self.assertEqual(len(result.points),5)
            self.assertEqual(result.points[2].x,145 if mode=='center' else 90)
            self.assertAlmostEqual(result.width*result.points[2].thickness,6)
            self.assertLess(m.distance(m.segment_point(a,0,.5),m.segment_point(result,0,.5)),1e-8)

    def test_close_preserves_existing_curve_and_removes_tip_taper(self):
        source=curve(taper_start=.5,taper_end=.8)
        result=t.close_stroke(source)
        self.assertEqual(len(result.points),4);self.assertEqual(result.taper_start+result.taper_end,0)
        self.assertEqual((result.points[0].x,result.points[0].y),(result.points[-1].x,result.points[-1].y))
        for i in range(2):
            for u in (.1,.5,.9):self.assert_same(m.segment_point(source,i,u),m.segment_point(result,i,u))
        with self.assertRaises(ValueError):t.close_stroke(result)

    def test_invalid_topology_is_non_mutating_and_limits_are_enforced(self):
        a,b=curve(),curve(200);before=[a.data(),b.data()]
        for args in ((a,[0,2],0),(a,[0],0),(a,[-1,0],0)):
            with self.assertRaises(ValueError):t.merge_points(*args)
        with self.assertRaises(ValueError):t.join_strokes(a,1,b,0)
        large=Stroke([Point(i,0) for i in range(m.MAX_POINTS)])
        with self.assertRaises(ValueError):t.join_strokes(large,len(large.points)-1,b,0)
        self.assertEqual([a.data(),b.data()],before)

    def test_selection_distinguishes_merge_join_close_and_rejects_branches(self):
        a,b=curve(),curve(200)
        keys={(a.uid,2),(b.uid,0)}
        self.assertEqual(t.selection_kind([a,b],keys,(b.uid,0),'join')[1],(b.uid,0))
        self.assertEqual(t.selection_kind([a,b],{(a.uid,0),(a.uid,2)},(a.uid,2),'join')[0],'close')
        with self.assertRaises(ValueError):t.selection_kind([a,b],{(a.uid,0),(a.uid,1),(b.uid,0)},(b.uid,0),'join')

    def test_new_topology_roundtrips_and_one_step_history_restores_sources(self):
        a,b=curve(width=10),curve(200,width=40)
        before=[a.data(),b.data()];history=m.History([a,b])
        joined,_=t.join_strokes(a,2,b,0)
        self.assertEqual(m.load_strokes([joined.data()])[0].data(),joined.data())
        history.commit([joined]);self.assertEqual([s.data() for s in history.undo()],before)
        self.assertEqual([s.data() for s in history.redo()],[joined.data()])

    def test_join_rejects_diameter_overflow_in_active_base_without_changing_sources(self):
        a,b=curve(width=.1),curve(200,width=2000)
        for point in b.points: point.thickness=2
        before=[a.data(),b.data()]
        with self.assertRaises(ValueError):t.join_strokes(a,2,b,0)
        self.assertEqual([a.data(),b.data()],before)


class EraserTests(unittest.TestCase):
    def test_swept_line_hit_includes_crossings_and_handles_stationary_cursor(self):
        self.assertEqual(e.segment_pair_distance(Point(0,0),Point(100,0),Point(50,-50),Point(50,50)),0)
        self.assertTrue(e.hit_center([Point(0,0),Point(100,0)],Point(50,-40),Point(50,40),5))
        self.assertFalse(e.hit_center([Point(0,0)],Point(20,0),Point(20,0),5))
        self.assertAlmostEqual(e.segment_pair_distance(Point(0,0),Point(100,0),Point(50,10),Point(80,10)),10)

    def test_point_eraser_preserves_geometry_pressure_and_has_stable_coverage(self):
        original=curve(width=20);baseline=t.prepared(original);result=copy.deepcopy(baseline)
        coverage={};point=Point(40,60)
        weights=e.point_weights(result,point,point,20,.5)
        self.assertTrue(e.reduce_points(result,baseline,weights,coverage))
        self.assertAlmostEqual(result.points[1].thickness,baseline.points[1].thickness*.5)
        data=result.data()
        for _ in range(100):self.assertFalse(e.reduce_points(result,baseline,weights,coverage))
        self.assertEqual(result.data(),data)
        full=e.point_weights(result,point,point,20,1);e.reduce_points(result,baseline,full,coverage)
        self.assertEqual(result.points[1].thickness,0)
        self.assertEqual(result.data()['points'],original.data()['points'])
        self.assertEqual([(p.handle_in,p.handle_out) for p in result.points],[(p.handle_in,p.handle_out) for p in baseline.points])
        self.assertEqual(result.points[0].thickness,baseline.points[0].thickness)
        self.assertEqual(m.load_strokes([result.data()])[0].data(),result.data())

    def test_minimum_is_baked_before_erase_so_zero_is_reachable(self):
        stroke=curve(width=20,minimum=.5);m.freeze_thickness(stroke)
        original=copy.deepcopy(stroke);t.bake_minimum(stroke)
        for i in range(2):
            for u in (0,.3,.8,1):
                old=m.segment_point(original,i,u);new=m.segment_point(stroke,i,u)
                self.assertAlmostEqual(new.thickness,.5+.5*old.thickness)
        result=copy.deepcopy(stroke);e.reduce_points(result,stroke,{1:1},{})
        self.assertEqual(result.minimum,0);self.assertEqual(result.points[1].thickness,0)


if __name__ == '__main__': unittest.main()
