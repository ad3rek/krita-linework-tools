# SPDX-License-Identifier: GPL-3.0-or-later
"""Measured hot picker/eraser queries and native preset reuse in isolated Krita."""
import copy, hashlib, json, math, os, statistics, time, traceback
from pathlib import Path
from krita import Krita, Extension
from PyQt5.QtCore import QTimer, QPointF
from PyQt5.QtWidgets import QApplication, QDialog
ROOT=Path(os.environ['LINEWORK_TEST_ROOT']).resolve()
class Probe(Extension):
 def setup(self): self.result={}; self.after(self.start,1800)
 def createActions(self,w): pass
 def after(self,fn,ms=100): QTimer.singleShot(ms,lambda:self.safe(fn))
 def safe(self,fn):
  try: fn()
  except Exception: self.result.update(result='fail',traceback=traceback.format_exc()); self.finish()
 def finish(self):
  (ROOT/'docs/validation/performance.json').write_text(json.dumps(self.result,indent=2))
  for d in Krita.instance().documents(): d.setModified(False)
  if hasattr(self,'window'): self.window.qwindow().close()
  QTimer.singleShot(300,QApplication.instance().quit)
 def timed(self,fn,count):
  times=[]
  for _ in range(3):
   begin=time.perf_counter()
   for i in range(count): fn(i)
   times.append((time.perf_counter()-begin)*1000/count)
  return statistics.median(times)
 def start(self):
  self.k=Krita.instance()
  for w in QApplication.topLevelWidgets():
   if w.metaObject().className()=='KisAutoSaveRecoveryDialog': QDialog.reject(w)
  if not self.k.activeDocument(): self.after(self.start); return
  self.window=self.k.activeWindow(); self.window.activate(); QApplication.setActiveWindow(self.window.qwindow())
  self.view=self.window.activeView()
  from linework.tools import select_tool,current_controller
  from linework.model import Point,Stroke,load_strokes,distance
  from linework.native_brush import capture_brush,NativeBrushRenderer
  from linework.eraser import point_weights
  select_tool(3); self.c=current_controller(self.window); o=self.c.overlay
  fixture=json.loads((ROOT/'fixture.json').read_text()); o.strokes=load_strokes(fixture)
  # Warm curve caches and then measure point picking over the same 743 paths.
  o.selection_mode='point'; o.selection.clear()
  positions=[Point((i*137)%833,(i*239)%1280) for i in range(300)]
  self.result['strokes']=len(o.strokes); self.result['anchors']=sum(len(s.points) for s in o.strokes)
  begin=time.perf_counter();o.hit_at(positions[0]);self.result['cold_point_pick_ms']=(time.perf_counter()-begin)*1000
  self.result['point_pick_ms']=self.timed(lambda i:o.hit_at(positions[i]),len(positions))
  def linear_pick(i):
   p=positions[i];threshold=o.pick_radius/o.zoom;best=None;best_distance=threshold
   for stroke in reversed(o.strokes):
    closest=min(range(len(stroke.points)),key=lambda j:distance(p,stroke.points[j]))
    d=distance(p,stroke.points[closest])
    if d<=threshold and (best is None or d<best_distance-1e-9):best=(stroke,closest);best_distance=d
   return best or (None,-1)
  assert all(o.hit_at(p)==linear_pick(i) for i,p in enumerate(positions))
  self.result['linear_point_pick_ms']=self.timed(linear_pick,len(positions))
  self.result['indexed_and_linear_point_picks_equal']='pass'
  def full_weights(i):
   p=positions[i]
   return {s.uid:point_weights(s,p,p,16,1) for s in o.strokes}
  def weights(i):
   p=positions[i]; radius=16
   if hasattr(o,'spatial_index'):
    idx=o.spatial_index(); keys=idx.anchors_in((p.x-radius,p.y-radius,p.x+radius,p.y+radius))
    groups={}
    for uid,index in keys: groups.setdefault(uid,[]).append(index)
    return {uid:point_weights(idx.strokes[uid],p,p,radius,1,indices) for uid,indices in groups.items()}
   return {s.uid:point_weights(s,p,p,radius,1) for s in o.strokes}
  self.result['point_eraser_query_ms']=self.timed(weights,len(positions))
  assert all({uid:w for uid,w in weights(i).items() if w}=={uid:w for uid,w in full_weights(i).items() if w} for i in range(len(positions)))
  self.result['linear_point_eraser_query_ms']=self.timed(full_weights,len(positions))
  self.result['indexed_and_linear_eraser_weights_equal']='pass'
  if hasattr(o,'spatial_index'):
   target=o.strokes[0];point=target.points[0];original_x=point.x
   def moved(i):
    point.x=original_x+i*.01;o.invalidate_spatial({target.uid});o.hit_at(point)
   self.result['pick_after_single_point_move_ms']=self.timed(moved,60)
   point.x=original_x;o.invalidate_spatial({target.uid});o.hit_at(point)
  # Warm the engine separately. Preview avoids the existing image cache/PNG.
  self.view.setCurrentBrushPreset(self.k.resources('preset')['u) Pixel Art'])
  self.k.action('erase_action').setChecked(False); brush=capture_brush(self.view)
  self.stroke=Stroke([Point(100,100,1),Point(220,180,.5),Point(330,130,1)],width=12,brush=brush)
  self.renderer=NativeBrushRenderer(self.view); self.renderer.render(self.stroke,preview=True)
  self.times=[]; self.times_uncached=[]; self.count=0; self.after(self.render_one)
 def render_one(self):
  self.stroke.points[1].y=180+self.count%3
  cached_available=hasattr(self.renderer,'preset_cache_stats') and self.renderer.preset_cache_stats() is not None
  modes=(False,True) if cached_available and self.count%2==0 else ((True,False) if cached_available else (True,))
  for cached in modes:
   if cached_available:self.renderer.use_preset_cache=cached
   begin=time.perf_counter(); self.renderer.render(self.stroke,preview=True)
   (self.times if cached else self.times_uncached).append((time.perf_counter()-begin)*1000)
  self.count+=1
  if self.count<40: self.after(self.render_one,1); return
  self.result['native_preview_median_ms']=statistics.median(self.times)
  self.result['native_preview_total_ms']=sum(self.times)
  if self.times_uncached:self.result['native_uncached_preview_median_ms']=statistics.median(self.times_uncached)
  if hasattr(self.renderer,'preset_cache_stats'):
   stats=self.renderer.preset_cache_stats(); self.result['preset_cache']=stats
   assert stats and stats['misses']==1 and stats['hits']==40,stats
   self.check_presets()
  self.renderer.close(); self.result.update(result='pass',krita=self.k.version()); self.finish()
 def pixels(self,stroke,cached):
  self.renderer.use_preset_cache=cached
  bounds,image,_=self.renderer.render(stroke,preview=True)
  ptr=image.constBits();ptr.setsize(image.byteCount())
  return (bounds.x(),bounds.y(),bounds.width(),bounds.height(),hashlib.sha256(bytes(ptr)).hexdigest())
 def check_presets(self):
  from linework.native_brush import ensure_thickness
  for explicit in (False,True,False):
   stroke=copy.deepcopy(self.stroke);stroke.width=27 if explicit else 12
   stroke.opacity=.6 if explicit else 1;stroke.color='#583aca' if explicit else '#202020'
   if explicit:ensure_thickness(stroke)
   assert self.pixels(stroke,False)==self.pixels(stroke,True)
  self.result['cached_and_uncached_pixels_equal_with_alternating_explicit_diameter_style']='pass'
  import xml.etree.ElementTree as ET
  for i in range(12):
   stroke=copy.deepcopy(self.stroke);xml=ET.fromstring(stroke.brush['xml']);xml.set('linework-cache-test',str(i));stroke.brush['xml']=ET.tostring(xml,encoding='unicode')
   assert self.pixels(stroke,False)==self.pixels(stroke,True)
  stats=self.renderer.preset_cache_stats();assert stats['entries']==8 and stats['xml_bytes']<=8*1024*1024
  self.result['xml_changes_invalidate_and_lru_cache_is_bounded']='pass'
  invalid=copy.deepcopy(self.stroke);invalid.brush['xml']='<broken'
  try:self.pixels(invalid,True)
  except ValueError:pass
  else:raise AssertionError('Invalid XML was accepted')
  assert self.pixels(self.stroke,False)==self.pixels(self.stroke,True)
  self.result['invalid_preset_does_not_poison_cache']='pass'
  self.renderer.close();assert self.renderer.preset_cache is None
  self.pixels(self.stroke,True);assert self.renderer.preset_cache_stats()['misses']==1
  self.result['cache_released_and_recreated_after_close']='pass'
Krita.instance().addExtension(Probe(Krita.instance()))
