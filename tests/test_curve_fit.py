"""Finished brush reduction: geometry and sensor signals, without Krita."""
import copy
import importlib
import math
from pathlib import Path
import sys
import types
import unittest

package = types.ModuleType('linework_fit_test')
package.__path__ = [str(Path(__file__).resolve().parents[1]/'linework')]
sys.modules[package.__name__] = package
model = importlib.import_module(package.__name__+'.model')
fit = importlib.import_module(package.__name__+'.curve_fit')
Point, Stroke = model.Point, model.Stroke


def line_path(points, **kwargs):
    stroke = Stroke(points, **kwargs)
    for a, b in zip(points, points[1:]):
        a.handle_out = (b.x-a.x)/3, (b.y-a.y)/3
        b.handle_in = (a.x-b.x)/3, (a.y-b.y)/3
    return stroke


def subdivided(stroke, count=600):
    """Many exact cubic pieces, as produced by the native helper."""
    controls = model.segment_controls(stroke, 0)
    vectors = [(p.x, p.y, p.pressure, model.thickness_factor(p)) for p in controls]
    result = copy.copy(stroke); result.points = []
    for i in range(count+1):
        t = i/count
        p = model.cubic_point(controls, t)
        derivative = fit._derivative(vectors, t)
        if i < count:
            p.handle_out = derivative[0]/(3*count), derivative[1]/(3*count)
            p.pressure_out = derivative[2]/(3*count)
            if p.thickness is not None: p.thickness_out = derivative[3]/(3*count)
        if i:
            p.handle_in = -derivative[0]/(3*count), -derivative[1]/(3*count)
            p.pressure_in = -derivative[2]/(3*count)
            if p.thickness is not None: p.thickness_in = -derivative[3]/(3*count)
        result.points.append(p)
    return result


class CurveFitTests(unittest.TestCase):
    def test_dense_s_in_all_modes_reduces_and_stays_subpixel(self):
        original = Stroke([Point(0, 0, .2, handle_out=(180, 0), pressure_out=.15),
                           Point(300, 220, .8, handle_in=(-180, 0), pressure_in=-.15)], width=12)
        for mode in range(4):
            stroke = subdivided(original)
            self.assertEqual(fit.compact_stroke(stroke, mode)[0], 601)
            self.assertLess(len(stroke.points), 35)
            self.assertEqual((stroke.points[0].x, stroke.points[0].y, stroke.points[0].pressure), (0, 0, .2))
            self.assertEqual((stroke.points[-1].x, stroke.points[-1].y, stroke.points[-1].pressure), (300, 220, .8))
            for i in range(81):
                p = model.segment_point(original, 0, i/80)
                error, segment, t = model.closest_location(stroke, p)
                q = model.segment_point(stroke, segment, t)
                self.assertLessEqual(error, fit.MODE_TOLERANCE[mode]+.001)
                self.assertLess(abs(p.pressure-q.pressure), .004)
            self.assertEqual(Stroke.from_data(stroke.data()).data(), stroke.data())

    def test_sharp_corners_remain_exact_anchors(self):
        points = [Point(i*.5, 0) for i in range(401)]
        points += [Point(200, i*.5) for i in range(1, 401)]
        points += [Point(200-i*.5, 200) for i in range(1, 401)]
        stroke = line_path(points)
        fit.compact_stroke(stroke, 3)
        self.assertEqual([(p.x, p.y) for p in stroke.points], [(0, 0), (200, 0), (200, 200), (0, 200)])

    def test_closed_loop_is_not_collapsed_to_a_dot(self):
        stroke = line_path([Point(100*math.cos(i*2*math.pi/1000), 100*math.sin(i*2*math.pi/1000), .6)
                            for i in range(1001)])
        fit.compact_stroke(stroke, 3)
        self.assertLess(len(stroke.points), 40)
        self.assertGreater(len(stroke.points), 4)
        for i in range(81):
            p = Point(100*math.cos(i*2*math.pi/80), 100*math.sin(i*2*math.pi/80))
            self.assertLess(model.closest_location(stroke, p)[0], .551)

    def test_pressure_pulse_and_stationary_sensor_changes_survive(self):
        stroke = line_path([Point(i*.5, 0, .2+.75*math.exp(-((i-300)/35)**2)) for i in range(601)], width=20)
        fit.compact_stroke(stroke, 3)
        self.assertLess(len(stroke.points), 100)
        for i in range(81):
            p = Point(i*300/80, 0)
            expected = .2+.75*math.exp(-((p.x*2-300)/35)**2)
            _, segment, t = model.closest_location(stroke, p)
            self.assertLess(abs(model.segment_point(stroke, segment, t).pressure-expected), .004)
        stationary = line_path([Point(20, 30, .2+i*.003) for i in range(101)] +
                               [Point(20, 30, .5-i*.003) for i in range(1, 101)])
        fit.compact_stroke(stationary, 3)
        self.assertLess(len(stationary.points), 40)
        pressures = [model.segment_point(stationary, s, i/100).pressure
                     for s in range(len(stationary.points)-1) for i in range(101)]
        self.assertGreater(max(pressures), .496)
        self.assertEqual((stationary.points[0].x, stationary.points[-1].x), (20, 20))

    def test_independent_diameter_and_pressure_have_separate_controls(self):
        original = Stroke([Point(0, 0, .3, handle_out=(90, 80), pressure_out=.1,
                                 thickness=.2, thickness_out=1.4),
                           Point(240, 70, .7, handle_in=(-90, -80), pressure_in=-.1,
                                 thickness=.5, thickness_in=.8)], width=25)
        stroke = subdivided(original)
        fit.compact_stroke(stroke, 2)
        self.assertLess(len(stroke.points), 50)
        for i in range(101):
            p = model.segment_point(original, 0, i/100)
            _, segment, t = model.closest_location(stroke, p)
            q = model.segment_point(stroke, segment, t)
            self.assertLess(abs(p.pressure-q.pressure), .004)
            self.assertLess(abs(p.thickness-q.thickness)*stroke.width, .12)
        self.assertEqual(Stroke.from_data(stroke.data()).data(), stroke.data())

    def test_tiny_tips_use_tighter_geometry_limits(self):
        original = Stroke([Point(0, 0, handle_out=(25, 5)),
                           Point(70, 20, handle_in=(-25, -5))], width=.5)
        stroke = subdivided(original, 300)
        fit.compact_stroke(stroke, 3)
        self.assertLess(len(stroke.points), 30)
        for i in range(81):
            p = model.segment_point(original, 0, i/80)
            self.assertLess(model.closest_location(stroke, p)[0], .041)

    def test_single_dots_short_paths_and_line_tools_are_unchanged(self):
        for stroke in (Stroke([Point(3, 4, .6)]), Stroke([Point(0, 0), Point(20, 30)]),
                       Stroke([Point(i, i) for i in range(10)], kind='line')):
            before = copy.deepcopy(stroke.data())
            fit.compact_stroke(stroke, 3)
            self.assertEqual(stroke.data(), before)

    def test_twenty_thousand_straight_anchors_and_metadata(self):
        stroke = line_path([Point(i*.05, 0, .7) for i in range(20000)],
                           brush={'engine':'krita-native','name':'test','filename':'test.kpp','xml':'<Preset/>'},
                           color='#28bbee', taper_start=.2, taper_end=.1)
        before = copy.deepcopy(stroke.data()); live = [Point(9, 10)]; stroke._live_points = live
        self.assertEqual(fit.compact_stroke(stroke, 3), (20000, 2))
        self.assertIs(stroke._live_points, live)
        after = stroke.data()
        for key in ('id', 'width', 'color', 'brush', 'opacity', 'minimum', 'taper_start', 'taper_end'):
            self.assertEqual(before[key], after[key])


if __name__ == '__main__': unittest.main()
