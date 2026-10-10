# SPDX-License-Identifier: GPL-3.0-or-later
import os
import copy,json,math,traceback,time
from pathlib import Path
from krita import Krita,Extension
from linework.qt import QTimer,QPointF,Qt,QEvent
from linework.qt import tablet_event,QKeyEvent,QMouseEvent
from linework.qt import QApplication,QDialog,QDockWidget
ROOT=Path(os.environ['LINEWORK_TEST_ROOT']).resolve()
class Probe(Extension):
 def setup(self):self.result={};self.tries=0;QTimer.singleShot(1800,lambda:self.safe(self.start))
 def createActions(self,w):pass
 def safe(self,f):
  try:f()
  except Exception:self.result.update(result='fail',traceback=traceback.format_exc());self.finish()
 def after(self,f,ms=100):QTimer.singleShot(ms,lambda:self.safe(f))
 def finish(self):
  (ROOT/'docs/validation/smoothing.json').write_text(json.dumps(self.result,indent=2))
  for d in Krita.instance().documents():d.setModified(False)
  if hasattr(self,'window'):self.window.qwindow().close()
  QTimer.singleShot(400,QApplication.instance().quit)
 def start(self):
  self.k=Krita.instance()
  for w in QApplication.topLevelWidgets():
   if w.metaObject().className()=='KisAutoSaveRecoveryDialog':QDialog.reject(w)
  for w in self.k.windows():QApplication.setActiveWindow(w.qwindow());w.activate()
  if not self.k.activeDocument():self.tries+=1;assert self.tries<40;self.after(self.start);return
  self.window=self.k.activeWindow();self.window.qwindow().resize(1500,1060)
  self.view=self.window.activeView();self.doc=self.view.document();self.source=self.doc.activeNode()
  self.before=bytes(self.source.pixelData(0,0,self.doc.width(),self.doc.height()))
  self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity']);self.view.setBrushSize(12);self.k.action('erase_action').setChecked(False)
  from linework.tools import select_tool,current_controller
  select_tool(0);self.c=current_controller(self.window);self.c.poll();assert self.c.overlay,self.c.status.text()
  from linework import native_smoothing
  values=native_smoothing.settings()
  if self.c.smoothing.variable_distance:
   values[0]=2;values[1]=80;values[9]=20;values[10]=0
   native_smoothing.settings(values);self.c.smoothing.reload()
   self.c.smoothing.fields[1].setValue(100)
   assert self.c.smoothing.fields[9].value()==20
   self.c.smoothing.fields[10].setChecked(True)
   self.c.smoothing.fields[1].setValue(80)
   assert self.c.smoothing.fields[9].value()==16
   shared=native_smoothing.settings()
   assert shared[1]==80 and shared[9]==16 and shared[10]==1
   self.result['variable_distance_and_aspect_ratio_share_native_settings']='pass'
  self.mode_count=self.c.smoothing.mode.count()
  from linework.model import closest_location,segment_point
  original_compact=native_smoothing.compact_stroke
  def audited(stroke,mode):
   before=copy.deepcopy(stroke);start=time.perf_counter()
   counts=original_compact(stroke,mode);elapsed=(time.perf_counter()-start)*1000
   self.latest={'before':counts[0],'after':counts[1],'milliseconds':elapsed}
   if len(stroke.points)>1 and self.mode<4:
    xy=pressure=0
    for i in range(50):
     index=min(len(before.points)-2,int(i*(len(before.points)-1)/50))
     p=segment_point(before,index,.37)
     e,j,t=closest_location(stroke,p);q=segment_point(stroke,j,t)
     xy=max(xy,e);pressure=max(pressure,abs(p.pressure-q.pressure))
    assert xy<.56,xy
    assert pressure<.004,pressure
    self.latest.update(max_position_error=xy,max_pressure_error=pressure)
   assert (before.points[0].x,before.points[0].y,before.points[0].pressure)==(stroke.points[0].x,stroke.points[0].y,stroke.points[0].pressure)
   assert (before.points[-1].x,before.points[-1].y,before.points[-1].pressure)==(stroke.points[-1].x,stroke.points[-1].y,stroke.points[-1].pressure)
   return counts
  native_smoothing.compact_stroke=audited
  self.mode=0;self.run_mode()
 def tablet(self,event,x,y,p):
  o=self.c.overlay;o.sync_transform();pos=o.image_to_widget.map(QPointF(x,y))
  ev=tablet_event(event,pos,p,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton if event!=QEvent.Type.TabletRelease else Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
  QApplication.sendEvent(self.c.native_widget,ev)
  assert self.c.overlay and not self.c._error,self.c.status.text()
 def key(self,key):
  QApplication.sendEvent(self.c.native_widget,QKeyEvent(QEvent.Type.ShortcutOverride,key,Qt.KeyboardModifier.NoModifier))
  QApplication.sendEvent(self.c.native_widget,QKeyEvent(QEvent.Type.KeyPress,key,Qt.KeyboardModifier.NoModifier))
 def run_mode(self):
  self.c.smoothing.mode.setCurrentIndex(self.mode)
  self.c.smoothing.fields[1].setValue(80 if self.mode==2 else 25)
  self.c.smoothing.fields[6].setChecked(False)
  self.c.smoothing.fields[7].setChecked(True)
  self.c.smoothing.fields[3].setChecked(True)
  self.c.smoothing.fields[8].setChecked(True)
  assert self.c.smoothing.fields[1].isVisible()==(self.mode in (2,3))
  assert self.c.smoothing.fields[2].isVisible()==(self.mode==2)
  assert self.c.smoothing.fields[5].isVisible()==(self.mode==3)
  self.c.poll();self.o=self.c.overlay;self.count=len(self.o.strokes);self.index=0
  self.tablet(QEvent.Type.TabletPress,120,100+110*self.mode,.2)
  self.after(self.move,8)
 def move(self):
  self.index+=1
  x=120+3*self.index;y=100+110*self.mode+(35*math.sin(self.index*2*math.pi/100))
  self.tablet(QEvent.Type.TabletMove,x,y,.2+.6*(self.index/100))
  if self.index<100:self.after(self.move,8)
  else:self.after(self.end,25)
 def end(self):
  self.tablet(QEvent.Type.TabletRelease,420,100+110*self.mode,0)
  assert len(self.o.strokes)==self.count+1
  s=self.o.strokes[-1]
  assert len(s.points)>1 and any(p.pressure<.99 for p in s.points)
  assert all(math.isfinite(v) for p in s.points for v in (p.x,p.y,p.pressure))
  assert self.o.smoother is None and self.o.renderer.stream is None
  if self.mode not in (2,4):assert abs(s.points[-1].x-420)<1e-6
  if self.mode==4:
   # Krita's native Pixel smoothing snaps coordinates to pixel centers.
   assert abs(s.points[-1].x-420.5)<1e-6
   assert abs(s.points[-1].y-(100+110*self.mode+.5))<1e-6
  if self.mode==0:assert all(abs(p.y-(100+110*self.mode))<=35.01 for p in s.points)
  if self.mode==1:assert any(abs((p.handle_out or (0,0))[1])>1e-3 for p in s.points)
  if self.mode==2:assert s.points[-1].pressure<.8
  if self.mode==3:
   assert not any(a.x==b.x and a.y==b.y and a.pressure==b.pressure for a,b in zip(s.points,s.points[1:]))
  assert len(s.points)<self.latest['before']*.7,(self.mode,self.latest)
  self.result[str(self.mode)]={'reduction':self.latest,'anchors':len(s.points),'first_pressure':s.points[0].pressure,'last_pressure':s.points[-1].pressure,'endpoint':[s.points[-1].x,s.points[-1].y], 'manual_handles':sum(p.handle_in is not None or p.handle_out is not None for p in s.points)}
  from linework.storage import read_layer
  assert [p.data() for p in read_layer(self.doc,self.c.layer)]==[p.data() for p in self.o.strokes]
  self.o.undo();assert len(self.o.strokes)==self.count
  self.o.redo();assert len(self.o.strokes)==self.count+1
  self.mode+=1
  if self.mode<self.mode_count:self.after(self.run_mode,100)
  else:self.after(self.cancel,100)
 def cancel(self):
  self.c.smoothing.mode.setCurrentIndex(3)
  self.count=len(self.o.strokes);self.data=[s.data() for s in self.o.strokes]
  self.tablet(QEvent.Type.TabletPress,130,560,.3);self.tablet(QEvent.Type.TabletMove,330,565,.7)
  self.key(Qt.Key.Key_Escape);assert self.o.smoother is None and self.o.draft is None and self.o.renderer.stream is None
  assert [s.data() for s in self.o.strokes]==self.data
  self.after(self.delay,100)
 def delay(self):
  assert [s.data() for s in self.o.strokes]==self.data
  self.result['escape_cancels_native_timers_and_preserves_layer']='pass'
  self.c.smoothing.fields[5].setValue(40);self.c.smoothing.fields[6].setChecked(True)
  self.c.smoothing.fields[7].setChecked(False)
  self.tablet(QEvent.Type.TabletPress,120,560,.3);self.tablet(QEvent.Type.TabletMove,125,560,.8)
  self.after(self.delay_end,100)
 def delay_end(self):
  assert self.o.draft and len(self.o.draft.points)==1
  self.tablet(QEvent.Type.TabletRelease,125,560,0)
  s=self.o.strokes[-1];assert len(s.points)==1 and abs(s.points[0].x-120)<1e-8
  self.result['delay_blocks_short_move_and_dot_keeps_nonzero_pressure']='pass'
  self.c.smoothing.fields[6].setChecked(False);self.c.smoothing.fields[7].setChecked(False)
  self.c.smoothing.fields[1].setValue(200)
  self.tablet(QEvent.Type.TabletPress,120,610,.2);self.tablet(QEvent.Type.TabletMove,420,610,.8)
  self.after(self.no_finish,15)
 def no_finish(self):
  self.tablet(QEvent.Type.TabletRelease,420,610,0)
  assert not self.c.smoothing.values[7]
  self.result['finish_line_disabled_preserves_native_endpoint']='pass'
  self.tablet(QEvent.Type.TabletPress,120,670,.2);self.tablet(QEvent.Type.TabletMove,420,670,.8)
  self.after(self.save_during,30)
 def save_during(self):
  count=len(self.o.strokes);path=ROOT/'examples/save-during-stroke.kra';assert self.doc.saveAs(str(path))
  assert self.c.overlay.smoother is None and self.c.overlay.draft is None
  assert len(self.c.overlay.strokes)==count+1
  self.result['save_during_stroke_flushes_native_geometry']='pass'
  self.after(self.other_tool,100)
 def other_tool(self):
  self.o=self.c.overlay
  self.tablet(QEvent.Type.TabletPress,130,720,.4);self.tablet(QEvent.Type.TabletMove,280,725,.6)
  from linework.tools import select_tool
  select_tool(3);assert self.c.overlay.smoother is None and self.c.overlay.draft is None
  from linework.native_smoothing import settings
  values=settings();values[0]=2;values[1]=60;values[2]=.3;settings(values)
  select_tool(0);assert self.c.smoothing.mode.currentIndex()==2 and self.c.smoothing.fields[1].value()==60
  self.result['tool_switch_flushes_and_shared_native_settings_reload']='pass'
  self.after(self.done,100)
 def done(self):
  self.c.smoothing.mode.setCurrentIndex(3);self.c.smoothing.fields[6].setChecked(True);self.c.smoothing.fields[7].setChecked(True)
  self.c._tablet_until=0
  pos=QPointF(260,390);QApplication.sendEvent(self.c.native_widget,QMouseEvent(QEvent.Type.MouseMove,pos,Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
  assert self.c.overlay.hover_pos==pos
  self.result['delay_indicator_tracks_native_canvas_hover']='pass'
  self.window.qwindow().grab().save(str(ROOT/'docs/images/smoothing-options.png'))
  path=ROOT/'examples/smoothing-final.kra';assert self.doc.saveAs(str(path))
  from linework.storage import read_layer
  loaded=self.k.openDocument(str(path));node=loaded.nodeByUniqueID(self.c.layer.uniqueId())
  assert [s.data() for s in read_layer(loaded,node)]==[s.data() for s in self.c.overlay.strokes]
  loaded.setModified(False);loaded.close()
  assert self.before==bytes(self.source.pixelData(0,0,self.doc.width(),self.doc.height()))
  self.result['tablet_events_native_modes_pressure_handles_history_roundtrip_and_bitmap']='pass'
  self.result['modes_tested']=self.mode_count
  self.doc.saveAs(str(ROOT/'examples/smoothing-and-points.kra'))
  self.result['result']='pass';self.finish()
Krita.instance().addExtension(Probe(Krita.instance()))
