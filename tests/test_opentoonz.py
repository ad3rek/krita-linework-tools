"""Differential validation against the pinned, unmodified OpenToonz core."""
import ctypes
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
import copy
from concurrent.futures import ThreadPoolExecutor
from test_vectorize import tracing,model,raster,capsule

root=Path(__file__).resolve().parents[1]
port=root/'linework/native/opentoonz'

def fixtures():
    def entry(name,w,h,pixels,mode=0,threshold=170,noise=0,penalty=.5,max_width=200):
        return name,w,h,pixels,mode,threshold,noise,penalty,max_width
    yield entry('capsule',180,90,raster(180,90,lambda x,y:capsule(x,y,(20,45),(160,45),7),white=True))
    yield entry('hole',150,150,raster(150,150,lambda x,y:abs(math.hypot(x-75,y-75)-42)<6,white=True))
    yield entry('junction',170,150,raster(170,150,lambda x,y:capsule(x,y,(25,80),(145,80),5) or capsule(x,y,(85,25),(85,80),5),white=True))
    yield entry('cross',180,180,raster(180,180,lambda x,y:capsule(x,y,(25,25),(155,155),5) or capsule(x,y,(25,155),(155,25),5),white=True))
    yield entry('width-ramp',200,100,raster(200,100,lambda x,y:capsule(x,y,(25,50),(170,50),lambda t:2+12*t)),mode=1)
    yield entry('corners',160,150,raster(160,150,lambda x,y:capsule(x,y,(25,25),(70,125),4) or capsule(x,y,(70,125),(140,50),4),white=True))
    yield entry('diagonal-ambiguities',110,110,raster(110,110,lambda x,y:(18<x<92 and abs(x-y)<2) or (45<x<53 and 15<y<90),white=True))
    yield entry('touching-frame',160,110,raster(160,110,lambda x,y:capsule(x,y,(0,30),(150,80),6),white=True))
    yield entry('noise-and-hole',140,110,raster(140,110,lambda x,y:(20<x<120 and 30<y<80 and not (55<x<57 and 50<y<52)) or (2<x<4 and 2<y<4),white=True),noise=12)
    yield entry('thickness-cutoff',150,120,raster(150,120,lambda x,y:20<x<130 and 20<y<100,white=True),max_width=12)
    yield entry('hsv-value-at-threshold',100,60,raster(100,60,lambda x,y:capsule(x,y,(15,30),(85,30),5),color=(10,20,170),white=True),threshold=170)
    yield entry('hsv-value-below-threshold',100,60,raster(100,60,lambda x,y:capsule(x,y,(15,30),(85,30),5),color=(10,20,169),white=True),threshold=170)
    for penalty in (0,3,9):
        yield entry('penalty-'+str(penalty),160,150,raster(160,150,lambda x,y:abs(math.hypot(x-80,y-75)-45)<5,white=True),penalty=penalty)
    alpha=bytearray(raster(180,100,lambda x,y:capsule(x,y,(25,50),(155,50),6),color=(255,255,255)))
    for y in range(100):
        for x in range(180):
            if alpha[4*(y*180+x)+3]:alpha[4*(y*180+x)+3]=100 if y<48 else 210
    yield entry('alpha-white-threshold',180,100,bytes(alpha),mode=1,threshold=128)

class OpenToonzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='linework-opentoonz-reference-')
        path=Path(cls.tmp.name)/'reference.so'
        up=port/'upstream/toonz/sources'
        sources=[root/'tests/opentoonz_reference.cpp']+[up/'toonzlib'/('tcenterline'+name+'.cpp') for name in ('polygonizer','skeletonizer','adjustments','tostrokes','colors')]
        sources.append(up/'common/tgeometry/tgeometry.cpp')
        subprocess.run(['g++','-std=c++17','-DLINUX','-O2','-fPIC','-shared','-pthread',
            '-I'+str(port/'compat'),'-I'+str(up/'include'),'-I'+str(up/'toonzlib'),
            *map(str,sources),'-Wl,--no-undefined','-o',str(path)],check=True,capture_output=True,timeout=90)
        cls.reference=ctypes.CDLL(str(path)).linework_opentoonz_reference
        cls.reference.argtypes=[ctypes.c_char_p]+[ctypes.c_int]*5+[ctypes.c_double]*2
        cls.reference.restype=ctypes.c_char_p
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_original_source_hashes_and_only_declared_host_patches(self):
        manifest=json.loads((port/'ORIGIN.json').read_text())
        for name,expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((port/'upstream'/name).read_bytes()).hexdigest(),expected,name)
        for original in (port/'upstream/toonz/sources/toonzlib').glob('tcenterline*'):
            production=port/'core'/original.name
            if not production.exists():continue
            text=production.read_text().replace('  delete borders;  // Host port: release the emptied container after each preview.\n','')
            text=text.replace('m_node(node), m_number(0)','m_node(node), m_number(rand())')
            text=text.replace('      if (thisVectorizer->isCanceled()) break;  // Host port: cleanup follows below.\n','')
            self.assertEqual(text,original.read_text(),original.name)

    def test_same_quadratic_controls_as_unmodified_upstream_for_all_fixtures(self):
        for name,w,h,pixels,mode,threshold,noise,penalty,max_width in fixtures():
            with self.subTest(name=name):
                expected=json.loads(self.reference(pixels,w,h,mode,threshold,noise,penalty,max_width))
                engine=tracing.TraceEngine()
                try:actual=engine.run(pixels,w,h,mode,threshold,noise,penalty,max_width,False)
                finally:engine.close()
                self.assertEqual([p['quadratics'] for p in actual['paths']],expected)
                self.assertTrue(all(p['color']==[0,0,0] and p['opacity']==1 for p in actual['paths']))

    def test_elevated_thickness_survives_split_save_and_affine_transform(self):
        fixture=next(f for f in fixtures() if f[0]=='width-ramp')
        _,w,h,pixels,mode,threshold,noise,penalty,max_width=fixture
        engine=tracing.TraceEngine()
        try:raw=engine.run(pixels,w,h,mode,threshold,noise,penalty,max_width)
        finally:engine.close()
        stroke=tracing.result_strokes(raw)[0];saved=model.Stroke.from_data(stroke.data())
        self.assertEqual(saved.data(),stroke.data())
        original=copy.deepcopy(stroke);split=.37;model.insert_point(stroke,0,split)
        for j in range(101):
            t=j/100;before=model.segment_point(original,0,t)
            after=model.segment_point(stroke,0,t/split) if t<=split else model.segment_point(stroke,1,(t-split)/(1-split))
            self.assertAlmostEqual(after.x,before.x,places=10);self.assertAlmostEqual(after.y,before.y,places=10)
            self.assertAlmostEqual(after.pressure,before.pressure,places=10)
        model.transform_stroke(saved,[2,.2,-.1,1.5,80,-20])
        for j in range(101):
            before=model.segment_point(original,0,j/100);after=model.segment_point(saved,0,j/100)
            self.assertAlmostEqual(after.pressure,before.pressure,places=10)

    def test_concurrent_workers_do_not_race_upstream_globals(self):
        cases=list(fixtures())[:4]*3
        expected={name:json.loads(self.reference(pixels,w,h,mode,threshold,noise,penalty,max_width))
                  for name,w,h,pixels,mode,threshold,noise,penalty,max_width in cases}
        def trace(fixture):
            name,w,h,pixels,mode,threshold,noise,penalty,max_width=fixture
            engine=tracing.TraceEngine()
            try:raw=engine.run(pixels,w,h,mode,threshold,noise,penalty,max_width,False)
            finally:engine.close()
            return name,[path['quadratics'] for path in raw['paths']]
        with ThreadPoolExecutor(max_workers=4) as workers:
            for name,actual in workers.map(trace,cases):self.assertEqual(actual,expected[name])

    def test_old_abi_requests_restart_instead_of_reading_missing_arguments(self):
        engine=tracing.TraceEngine()
        try:
            old=engine.lib.linework_trace_run
            old.argtypes=[ctypes.c_void_p,ctypes.c_char_p]+[ctypes.c_int]*5
            self.assertEqual(old(engine.handle,bytes(400),10,10,1,128,0),0)
            self.assertIn('reabra o Krita',engine.lib.linework_trace_error(engine.handle).decode())
        finally:engine.close()

if __name__=='__main__':unittest.main()
