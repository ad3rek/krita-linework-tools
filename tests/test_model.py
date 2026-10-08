"""Geometry checks without requiring Krita or Qt."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest
import copy

path = Path(__file__).resolve().parents[1]/"linework/model.py"
spec = importlib.util.spec_from_file_location("linework_model_test", path)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)
Point, Stroke = model.Point, model.Stroke


class GeometryTests(unittest.TestCase):
    def test_thickness_edit_preserves_pressure_and_uses_pixels(self):
        s = Stroke([Point(0, 0, .2), Point(100, 0, .8)], width=20, kind='line')
        model.freeze_thickness(s)
        model.set_point_thickness(s, 0, 35)
        self.assertEqual([p.pressure for p in s.points], [.2, .8])
        self.assertEqual(s.points[0].thickness, 1.75)
        self.assertAlmostEqual(model.outline(s)[0][1], 17.5)
        self.assertEqual(model.load_strokes([s.data()])[0].data(), s.data())

    def test_imported_radius_profile_is_frozen_without_reshaping(self):
        s = Stroke([Point(0, 0, .2, pressure_out=.6), Point(100, 20, .8, pressure_in=-.3)])
        before = model.outline(s)
        model.freeze_thickness(s)
        for new, old in zip(model.outline(s), before):
            self.assertLess(math.dist(new, old), 1e-10)
        self.assertEqual(s.points[0].thickness_out, .6)
        self.assertEqual(s.points[1].thickness_in, -.3)

    def test_insertion_splits_independent_thickness_and_pressure_exactly(self):
        s = Stroke([Point(0, 0, .2, thickness=1.7, thickness_out=-1.1),
                    Point(100, 20, .8, thickness=.3, thickness_in=.8)])
        before = copy.deepcopy(s); t = .37
        model.insert_point(s, 0, t)
        for j in range(101):
            u = j/100
            old = model.segment_point(before, 0, u)
            new = model.segment_point(s, 0, u/t) if u <= t else model.segment_point(s, 1, (u-t)/(1-t))
            self.assertLess(model.distance(old, new), 1e-9)
            self.assertAlmostEqual(new.thickness, old.thickness)
            self.assertAlmostEqual(new.pressure, old.pressure)

    def test_same_pixel_width_across_different_base_widths_and_history(self):
        a, b = Stroke([Point(0, 0, .4)], width=8), Stroke([Point(100, 0, .9)], width=32)
        history = model.History([a, b])
        for s in (a, b):
            model.freeze_thickness(s); model.set_point_thickness(s, 0, 12)
            self.assertEqual(s.width*model.thickness_factor(s.points[0]), 12)
        history.commit([a, b])
        self.assertTrue(all(p.thickness is None for s in history.undo() for p in s.points))
        self.assertEqual([s.data() for s in history.redo()], [a.data(), b.data()])
        model.transform_stroke(a, [2, 0, 0, 2, 0, 0])
        self.assertEqual(a.width*a.points[0].thickness, 24)

    def test_rejects_partial_or_invalid_thickness_profile(self):
        s = Stroke([Point(0, 0), Point(100, 0)])
        for profile in ([[1, None, None]], [[None, None, None]]*2,
                        [[-1, None, None]]*2, [[float('nan'), None, None]]*2):
            data = s.data(); data['thickness_profile'] = profile
            with self.assertRaises(ValueError): model.load_strokes([data])

    def test_affine_transform_preserves_curve_controls_and_pressure(self):
        s = Stroke([Point(10,30,.2),Point(83,117,.7),Point(201,-24,.9)],width=12)
        original = copy.deepcopy(s)
        model.transform_stroke(s,[2,.4,-.2,.7,80,-12])
        self.assertAlmostEqual(s.width,12*math.sqrt(1.48))
        for i in range(2):
            for t in (0,.25,.5,.9,1):
                before=model.segment_point(original,i,t);after=model.segment_point(s,i,t)
                self.assertAlmostEqual(after.x,2*before.x-.2*before.y+80)
                self.assertAlmostEqual(after.y,.4*before.x+.7*before.y-12)
                self.assertAlmostEqual(after.pressure,before.pressure)

    def test_transform_rejects_singular_matrix_before_modifying_data(self):
        s=Stroke([Point(10,30),Point(100,120)],width=8)
        before=s.data()
        with self.assertRaises(ValueError):model.transform_stroke(s,[0,0,0,1,40,60])
        self.assertEqual(s.data(),before)
        model.transform_stroke(s,[-1,0,0,1,0,0])
        self.assertEqual(s.width,8)
        self.assertEqual(s.points[0].x,-10)

    def test_legacy_automatic_curve_keeps_hermite_geometry(self):
        s = Stroke([Point(10, 30, .2), Point(83, 117, .7), Point(201, -24, .9), Point(250, 40)])
        for i, (a, b) in enumerate(zip(s.points, s.points[1:])):
            previous, following = s.points[max(0, i-1)], s.points[min(len(s.points)-1, i+2)]
            length = model.distance(a, b)
            f0 = length/(model.distance(previous, a)+length)
            f2 = length/(length+model.distance(b, following))
            for t in (0, .13, .5, .83, 1):
                p = model.segment_point(s, i, t)
                h0, h1, h2, h3 = 2*t**3-3*t*t+1, -2*t**3+3*t*t, t**3-2*t*t+t, t**3-t*t
                for axis in ("x", "y"):
                    expected = (h0*getattr(a, axis)+h1*getattr(b, axis)+
                        h2*(getattr(b, axis)-getattr(previous, axis))*f0+
                        h3*(getattr(following, axis)-getattr(a, axis))*f2)
                    self.assertAlmostEqual(getattr(p, axis), expected, places=10)

    def test_handles_change_curve_and_follow_anchor_translation(self):
        s = Stroke([Point(0, 0, handle_out=(0, 100)), Point(100, 0, handle_in=(0, 100))])
        p = model.segment_point(s, 0, .5)
        self.assertAlmostEqual(p.x, 50)
        self.assertAlmostEqual(p.y, 75)
        for point in s.points:
            point.x += 30; point.y -= 20
        q = model.segment_point(s, 0, .5)
        self.assertAlmostEqual(q.x, p.x+30); self.assertAlmostEqual(q.y, p.y-20)

    def test_insertion_preserves_whole_curve_and_pressure(self):
        for manual in (False, True):
            s = Stroke([Point(10, 30, .2), Point(83, 117, .7), Point(201, -24, .9), Point(250, 40)])
            if manual:
                s.points[1].handle_out = (160, -180)
                s.points[2].handle_in = (-50, -20)
            before = copy.deepcopy(s)
            t = .37
            self.assertEqual(model.insert_point(s, 1, t), 2)
            self.assertAlmostEqual(s.points[2].pressure, .7*(1-t)+.9*t)
            for segment in range(3):
                for j in range(101):
                    u = j/100
                    expected = model.segment_point(before, segment, u)
                    if segment != 1:
                        actual = model.segment_point(s, segment if segment < 1 else segment+1, u)
                    else:
                        actual = model.segment_point(s, 1, u/t) if u <= t else model.segment_point(s, 2, (u-t)/(1-t))
                    self.assertLess(model.distance(actual, expected), 1e-9)
                    self.assertAlmostEqual(actual.pressure, expected.pressure)

    def test_insertion_uses_actual_curve_and_avoids_duplicate_endpoints(self):
        s = Stroke([Point(0, 0, .2, handle_out=(0, 100)), Point(100, 0, .9, handle_in=(0, 100))])
        d, index, t = model.closest_location(s, Point(50, 75))
        self.assertLess(d, .001); self.assertEqual(index, 0); self.assertAlmostEqual(t, .5, places=4)
        model.insert_point(s, index, t)
        self.assertAlmostEqual(s.points[1].y, 75, places=4)
        self.assertEqual(model.insert_point(s, 0, 0), 0)
        self.assertEqual(model.insert_point(s, 0, 1), 1)
        self.assertEqual(len(s.points), 3)

    def test_handles_roundtrip_validation_and_history(self):
        s = Stroke([Point(0, 0, handle_out=(50, 60)), Point(100, 20, handle_in=(-30, 0))])
        self.assertEqual(model.load_strokes([s.data()])[0].data(), s.data())
        history = model.History([s])
        s.points[0].handle_out = (20, 80); history.commit([s])
        self.assertEqual(history.undo()[0].points[0].handle_out, (50, 60))
        self.assertEqual(history.redo()[0].points[0].handle_out, (20, 80))
        for invalid in ([[None, [float("nan"), 0]], [None, None]],
                        [[None, [1]], [None, None]], [[None, None]]):
            data = s.data(); data["handles"] = invalid
            with self.assertRaises(ValueError): model.load_strokes([data])

    def test_pressure_changes_outline_width(self):
        stroke = Stroke([Point(0, 0, .2), Point(100, 0, 1)], width=20, kind="line")
        polygon = model.outline(stroke)
        self.assertAlmostEqual(polygon[0][1], 2)
        center = model.samples(stroke)
        self.assertAlmostEqual(polygon[len(center)-1][1], 10)

    def test_dot_and_repeated_points_are_finite(self):
        for points in ([Point(5, 6)], [Point(5, 6, 0), Point(5, 6, 1)],
                       [Point(0, 0), Point(20, 0), Point(0, 0)]):
            polygon = model.outline(Stroke(points))
            self.assertTrue(polygon)
            self.assertTrue(all(math.isfinite(v) for pair in polygon for v in pair))

    def test_pressure_extreme_survives_simplification(self):
        points = [Point(0, 0, .1), Point(50, 0, 1), Point(100, 0, .1)]
        result = model.simplify(points, 1, 10)
        self.assertEqual(len(result), 3)

    def test_taper_reaches_zero_at_endpoints(self):
        s = Stroke([Point(0, 0), Point(100, 0)], taper_start=1, taper_end=1)
        polygon, center = model.outline(s), model.samples(s)
        self.assertEqual(polygon[0], (0, 0))
        self.assertEqual(polygon[len(center)-1], (100, 0))

    def test_roundtrip_editable_properties(self):
        s = Stroke([Point(10, 20, .5), Point(100, 90, 1)], width=24,
                   taper_end=.7, opacity=.4, color="#5599ee")
        self.assertEqual(model.load_strokes([s.data()])[0].data(), s.data())

    def test_reject_invalid_pressure_and_duplicate_ids(self):
        s = Stroke([Point(0, 0)])
        invalid = s.data()
        invalid["points"][0][2] = float("nan")
        with self.assertRaises(ValueError):
            model.load_strokes([invalid])
        with self.assertRaises(ValueError):
            model.load_strokes([s.data(), s.data()])

    def test_history_restores_geometry_and_pressure(self):
        s = Stroke([Point(0, 0, .3)])
        history = model.History([s])
        s.width = 35
        s.points[0].pressure = 1.2
        history.commit([s])
        previous = history.undo()
        self.assertEqual(previous[0].width, 8)
        self.assertEqual(previous[0].points[0].pressure, .3)
        self.assertEqual(history.redo()[0].width, 35)

    def test_svg_preserves_physical_document_scale(self):
        s = Stroke([Point(0, 0), Point(100, 0)])
        text = model.svg([s], 1200, 800, 300, 300)
        self.assertIn('width="288.00000000pt"', text)
        self.assertIn('height="192.00000000pt"', text)
        self.assertIn('viewBox="0 0 1200 800"', text)

    def test_native_preset_roundtrip_preserves_settings(self):
        s = Stroke([Point(10, 20, .4)], brush={"engine": "krita-native", "name": "Pencil",
            "filename": "Pencil.kpp", "xml": "<Preset/>", "flow": .6})
        restored = model.load_strokes([s.data()])[0]
        self.assertEqual(restored.data(), s.data())
        s.brush["flow"] = float("nan")
        with self.assertRaises(ValueError):
            model.load_strokes([s.data()])


if __name__ == "__main__":
    unittest.main()
