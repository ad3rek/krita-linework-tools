"""Native extraction and editable cubic geometry, without a Krita process."""
import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest

root=Path(__file__).resolve().parents[1]/'linework'
pkg=types.ModuleType('trace_test');pkg.__path__=[str(root)];sys.modules['trace_test']=pkg
for name in ('model','tracing'):
    spec=importlib.util.spec_from_file_location('trace_test.'+name,root/(name+'.py'))
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
model=sys.modules['trace_test.model'];tracing=sys.modules['trace_test.tracing']

def raster(width,height,inside,color=(0,0,0),white=False):
    data=bytearray()
    for y in range(height):
        for x in range(width):
            if inside(x+.5,y+.5):data.extend((color[2],color[1],color[0],255))
            else:data.extend((255,255,255,255) if white else (0,0,0,0))
    return bytes(data)

def capsule(x,y,a,b,r):
    p=model.Point(x,y);d,t=model.segment_distance(p,model.Point(*a),model.Point(*b))
    radius=r(t) if callable(r) else r
    return d<=radius

class VectorizeTests(unittest.TestCase):
    def trace(self,pixels,w,h,mode=1,noise=0,penalty=.5,threshold=200):
        engine=tracing.TraceEngine()
        try:
            raw=engine.run(pixels,w,h,mode,threshold,noise,penalty=penalty)
            return raw,tracing.result_strokes(raw)
        finally:engine.close()

    def test_straight_line_center_and_thickness(self):
        pixels=raster(160,80,lambda x,y:capsule(x,y,(20,40),(140,40),5))
        raw,strokes=self.trace(pixels,160,80)
        self.assertEqual(len(strokes),1)
        s=strokes[0];self.assertLess(len(s.points),8)
        self.assertLess(abs(s.width-10),1.5)
        self.assertTrue(all(abs(p.y-40)<2 for p in model.samples(s)))

    def test_varying_width_survives_as_pressure(self):
        pixels=raster(190,90,lambda x,y:capsule(x,y,(25,45),(160,45),lambda t:2+7*t))
        raw,strokes=self.trace(pixels,190,90)
        self.assertEqual(len(strokes),1)
        s=strokes[0];pressures=[p.pressure for p in s.points]
        self.assertGreater(max(pressures)-min(pressures),.5)
        self.assertGreater(s.width,15)
        self.assertTrue(any(p.handle_out is not None for p in s.points))

    def test_junction_keeps_all_three_arms(self):
        pixels=raster(140,120,lambda x,y:capsule(x,y,(20,65),(120,65),4) or capsule(x,y,(70,20),(70,65),4))
        raw,strokes=self.trace(pixels,140,120)
        arms=[s for s in strokes if sum(model.distance(a,b) for a,b in zip(s.points,s.points[1:]))>15]
        self.assertEqual(len(arms),3)
        for s in arms:
            self.assertLess(min(model.distance(p,model.Point(70,65)) for p in (s.points[0],s.points[-1])),4)

    def test_cycle_stays_closed_and_editable(self):
        pixels=raster(120,120,lambda x,y:abs(math.hypot(x-60,y-60)-32)<=4)
        raw,strokes=self.trace(pixels,120,120)
        self.assertEqual(len(strokes),1)
        self.assertLess(model.distance(strokes[0].points[0],strokes[0].points[-1]),1e-9)
        self.assertGreaterEqual(len(strokes[0].points),4)
        self.assertEqual(model.load_strokes([strokes[0].data()])[0].data(),strokes[0].data())

    def test_noise_removal_keeps_main_ink_and_source(self):
        pixels=raster(140,70,lambda x,y:capsule(x,y,(20,35),(120,35),3) or (5<x<7 and 5<y<7))
        before=bytes(pixels)
        _,with_noise=self.trace(pixels,140,70,noise=0)
        _,clean=self.trace(pixels,140,70,noise=8)
        self.assertEqual(len(clean),1);self.assertGreater(len(with_noise),len(clean))
        self.assertEqual(pixels,before)

    def test_white_background_and_alpha_keep_color(self):
        for white,mode in ((True,0),(False,1)):
            pixels=raster(130,70,lambda x,y:capsule(x,y,(20,35),(110,35),4),color=(30,60,170),white=white)
            raw,strokes=self.trace(pixels,130,70,mode)
            self.assertEqual(len(strokes),1);self.assertEqual(strokes[0].color,'#1e3caa')

    def test_cancellation_and_empty_image(self):
        engine=tracing.TraceEngine()
        try:
            engine.cancel()
            with self.assertRaises(InterruptedError):engine.run(bytes(400),10,10,1,128,0)
        finally:engine.close()
        _,strokes=self.trace(bytes(400),10,10)
        self.assertEqual(strokes,[])

    def test_quadratic_geometry_and_thickness_elevation_is_exact(self):
        raw={'algorithm':'opentoonz-centerline','paths':[{'color':[10,20,30],'opacity':.7,
            'quadratics':[[2,5,1],[35,70,9],[80,10,2],[120,-40,3],[170,50,7]]}]}
        s=tracing.result_strokes(raw,offset=(17,23),opacity=.5)[0]
        for i in range(2):
            a,c,b=raw['paths'][0]['quadratics'][2*i:2*i+3]
            for j in range(101):
                t=j/100;u=1-t;p=model.segment_point(s,i,t)
                for axis,shift in ((0,17),(1,23)):
                    self.assertAlmostEqual((p.x,p.y)[axis],u*u*a[axis]+2*u*t*c[axis]+t*t*b[axis]+shift,places=10)
                self.assertAlmostEqual(p.pressure*s.width/2,u*u*a[2]+2*u*t*c[2]+t*t*b[2],places=10)
        self.assertEqual(s.opacity,.35)

if __name__=='__main__':unittest.main()
