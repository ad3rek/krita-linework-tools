# SPDX-License-Identifier: GPL-3.0-or-later
import os
import copy,hashlib,json,time,traceback,math
from pathlib import Path
from krita import Krita,Extension
from PyQt5.QtCore import QTimer,Qt,QPointF,QEvent
from PyQt5.QtGui import QMouseEvent,QKeyEvent
from PyQt5.QtWidgets import QApplication,QDialog,QDockWidget
from PyQt5.QtTest import QTest
ROOT=Path(os.environ['LINEWORK_TEST_ROOT']).resolve()
class Probe(Extension):
 def setup(self):self.result={};self.tries=0;QTimer.singleShot(1800,lambda:self.safe(self.start))
 def createActions(self,w):pass
 def safe(self,fn):
  try:fn()
  except Exception:self.result.update(result='fail',traceback=traceback.format_exc());self.finish()
 def after(self,fn,ms=100):QTimer.singleShot(ms,lambda:self.safe(fn))
 def wait_update(self,fn):
  if self.c._brush_change:self.after(lambda:self.wait_update(fn));return
  assert self.c.overlay and not self.c._error,self.c.status.text();fn()
 def finish(self):
  (ROOT/'docs/validation/multi-point.json').write_text(json.dumps(self.result,indent=2))
  for doc in Krita.instance().documents():doc.setModified(False)
  if hasattr(self,'window'):self.window.qwindow().close()
  QTimer.singleShot(300,QApplication.instance().quit)
 def data(self):return [s.data() for s in self.c.overlay.strokes]
 def mouse(self,kind,point,mod=Qt.NoModifier):
  o=self.c.overlay;o.sync_transform();pos=o.image_to_widget.map(QPointF(*point))
  button=Qt.NoButton if kind==QEvent.MouseMove else Qt.LeftButton
  buttons=Qt.NoButton if kind==QEvent.MouseButtonRelease else Qt.LeftButton
  event=QMouseEvent(kind,pos,button,buttons,mod)
  actual=o.widget_to_image.map(event.localPos())
  if kind==QEvent.MouseButtonPress:self.event_start=actual
  if kind==QEvent.MouseMove:self.event_delta=actual-self.event_start
  QApplication.sendEvent(self.c.native_widget,event)
  assert self.c.overlay and not self.c._error,self.c.status.text()
 def click(self,point,mod=Qt.NoModifier):
  self.mouse(QEvent.MouseButtonPress,point,mod);self.mouse(QEvent.MouseButtonRelease,point,mod)
 def key(self,key,mod=Qt.NoModifier):
  QApplication.sendEvent(self.c.native_widget,QKeyEvent(QEvent.ShortcutOverride,key,mod))
  QApplication.sendEvent(self.c.native_widget,QKeyEvent(QEvent.KeyPress,key,mod))
 def alpha(self,x,y):return bytes(self.layer.projectionPixelData(x,y,1,1))[3]
 def start(self):
  self.k=Krita.instance()
  for w in QApplication.topLevelWidgets():
   if w.metaObject().className()=='KisAutoSaveRecoveryDialog':QDialog.reject(w)
  for w in self.k.windows():QApplication.setActiveWindow(w.qwindow());w.activate()
  if not self.k.activeDocument():
   self.tries+=1;assert self.tries<40;self.after(self.start);return
  self.window=self.k.activeWindow();self.window.qwindow().resize(1450,1020)
  self.view=self.window.activeView();self.doc=self.view.document();self.source=self.doc.activeNode()
  self.source_before=bytes(self.source.pixelData(0,0,self.doc.width(),self.doc.height()))
  self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
  self.k.action('erase_action').setChecked(False)
  from linework.tools import select_tool,current_controller
  from linework.model import Stroke,Point
  from linework.native_brush import capture_brush,NativeBrushRenderer
  from linework.storage import write_layer
  select_tool(3);self.c=current_controller(self.window);self.layer=self.c.create_native_layer(self.doc)
  brush=capture_brush(self.view);strokes=[]
  for y,press,width,color,preset in [(180,[.25,.6,.9],18,'#203040',brush),(350,[.65,.45,.8],24,'#274b72',brush),(520,[.4,.4,.4],30,'#804020',None)]:
   pts=[Point(150,y,press[0],handle_out=(50,0),pressure_out=.04),
        Point(300,y,press[1],handle_in=(-50,0),handle_out=(50,0),pressure_in=-.05,pressure_out=.07),
        Point(450,y,press[2],handle_in=(-50,0),pressure_in=-.06)]
   strokes.append(Stroke(pts,width=width,color=color,brush=copy.deepcopy(preset)))
  renderer=NativeBrushRenderer(self.view);write_layer(self.doc,self.layer,strokes,renderer);renderer.close()
  self.uids=[s.uid for s in strokes];self.initial=[s.data() for s in strokes]
  self.k.action('InteractionTool').trigger();self.after(self.native_select,400)
 def native_select(self):
  shapes={s.name():s for s in self.layer.shapes()}
  for s in shapes.values():s.deselect()
  shapes['lw_'+self.uids[0]].select();shapes['lw_'+self.uids[1]].select()
  assert sum(s.isSelected() for s in shapes.values())==2
  from linework.tools import select_tool
  select_tool(3);self.after(self.inherited,300)
 def inherited(self):
  from linework.tools import current_controller
  self.c=current_controller(self.window);self.c.poll();o=self.c.overlay
  assert o and o.selection.ids()==set(self.uids[:2]),{'selection':o.selection.ids() if o else None,'status':self.c.status.text()}
  assert len(o.selected_point_refs())==6
  assert self.c.controls['width'].mixed and self.c.controls['width'].lineEdit().text()=='', {'widths':[s.width for s in o.selected_strokes()], 'mixed':self.c.controls['width'].mixed,'text':self.c.controls['width'].lineEdit().text()}
  assert self.c.thickness.mixed
  self.result['native_shape_selection_inherited_two_curves_six_anchors']='pass'
  self.before=self.data();self.depth=len(o.history.undo_stack)
  self.c.controls['width'].setValue(32);self.after(lambda:self.wait_update(self.width_done))
 def width_done(self):
  o=self.c.overlay
  assert [s.width for s in o.strokes]==[32,32,30]
  assert len(o.history.undo_stack)==self.depth+1 and o.selection.ids()==set(self.uids[:2])
  expected=copy.deepcopy(self.before);expected[0]['width']=expected[1]['width']=32
  assert self.data()==expected
  o.undo();assert self.data()==self.before and o.selection.ids()==set(self.uids[:2])
  o.redo();assert self.data()==expected
  self.result['bulk_width_only_selected_curves_one_undo_redo']='pass'
  o.undo();assert self.c.controls['width'].mixed
  representative=self.c.controls['width'].value()
  edit=self.c.controls['width'].lineEdit();QTest.mouseClick(edit,Qt.LeftButton)
  QTest.keyClick(edit,Qt.Key_A,Qt.ControlModifier);QTest.keyClicks(edit,str(representative));QTest.keyClick(edit,Qt.Key_Return)
  self.representative=representative;self.after(lambda:self.wait_update(self.same_value_done))
 def same_value_done(self):
  assert [s.width for s in self.c.overlay.strokes[:2]]==[self.representative]*2
  assert not self.c.controls['width'].mixed
  self.result['mixed_value_accepts_typing_same_as_primary']='pass'
  self.c.overlay.undo()  # Restore the two different base widths before editing diameters.
  self.click((150,180),Qt.ShiftModifier);assert len(self.c.overlay.selected_point_refs())==5
  self.click((150,180),Qt.ShiftModifier);assert len(self.c.overlay.selected_point_refs())==6
  self.click((900,650));assert not self.c.overlay.selection.ids()
  self.click((150,180));self.click((150,350),Qt.ShiftModifier)
  assert len(self.c.overlay.selected_point_refs())==2 and len(self.c.overlay.selected_strokes())==2
  assert self.c.thickness.mixed
  self.result['shift_add_toggle_individual_anchors_across_curves']='pass'
  self.points_before=self.data();self.c.thickness.setValue(10)
  self.after(lambda:self.wait_update(self.pressure_done))
 def pressure_done(self):
  expected=self.data()
  for old,new in zip(self.points_before,expected):
   stripped=copy.deepcopy(new);stripped.pop('thickness_profile',None)
   assert stripped==old,(stripped,old)
  for s in self.c.overlay.strokes[:2]:assert math.isclose(s.width*s.points[0].thickness,10,abs_tol=1e-8)
  assert expected[2]==self.points_before[2]
  assert self.c.overlay.strokes[0].points[0].thickness!=self.c.overlay.strokes[1].points[0].thickness
  self.c.overlay.undo();assert self.data()==self.points_before
  self.c.overlay.redo();assert self.data()==expected
  self.result['same_pixel_width_across_bases_preserves_pressure_and_handles']='pass'
  self.drag_before=self.data();self.drag_svg={s.name():s.toSvg() for s in self.layer.shapes()}
  self.mouse(QEvent.MouseButtonPress,(150,180));o=self.c.overlay
  assert o.drag=='point' and len(o._edit_original)==2
  assert self.alpha(150,180)==0 and self.alpha(150,350)==0 and self.alpha(300,520)>0
  assert {s.name():s.toSvg() for s in self.layer.shapes()}==self.drag_svg
  self.mouse(QEvent.MouseMove,(180,200));o.refresh_native_preview();self.after(self.drag_moved,200)
 def drag_moved(self):
  o=self.c.overlay
  assert len(o.native_previews)==2
  expected=copy.deepcopy(self.drag_before)
  for s in expected[:2]:s['points'][0][0]+=self.event_delta.x();s['points'][0][1]+=self.event_delta.y()
  actual=self.data()
  for a,b in zip(actual[:2],expected[:2]):
   for axis in (0,1):assert math.isclose(a['points'][0][axis],b['points'][0][axis],abs_tol=1e-8), (a['points'][0],b['points'][0],self.event_delta.x(),self.event_delta.y(),o.last_doc)
   a['points'][0][:2]=b['points'][0][:2]
  assert actual==expected
  self.key(Qt.Key_Escape);assert self.data()==self.drag_before
  assert {s.name():s.toSvg() for s in self.layer.shapes()}==self.drag_svg
  assert self.alpha(150,180)>0 and self.alpha(150,350)>0
  assert len(o.selected_point_refs())==2
  self.result['multi_point_drag_hides_both_originals_and_escape_restores']='pass'
  from linework.tools import select_tool
  select_tool(4)
  self.mouse(QEvent.MouseButtonPress,(150,180));self.mouse(QEvent.MouseMove,(150,160));self.mouse(QEvent.MouseButtonRelease,(150,160))
  actual=self.data()
  for old,new in zip(self.drag_before,actual):
   old0=copy.deepcopy(old);new0=copy.deepcopy(new)
   old0.pop('thickness_profile',None);new0.pop('thickness_profile',None)
   assert old0==new0
  for s in self.c.overlay.strokes[:2]:assert math.isclose(s.width*s.points[0].thickness,10-self.event_delta.y(),abs_tol=1e-8)
  self.result['group_thickness_drag_adds_same_pixel_delta']='pass'
  self.rectangle_depth=len(self.c.overlay.history.undo_stack)
  self.mouse(QEvent.MouseButtonPress,(110,150));assert self.c.overlay.drag=='select'
  self.mouse(QEvent.MouseMove,(330,380));self.mouse(QEvent.MouseButtonRelease,(330,380))
  assert len(self.c.overlay.selected_point_refs())==4 and len(self.c.overlay.history.undo_stack)==self.rectangle_depth
  self.result['rectangle_selects_four_anchors_without_history']='pass'
  select_tool(3);before=self.data();self.key(Qt.Key_Delete)
  assert [len(s.points) for s in self.c.overlay.strokes]==[1,1,3]
  self.c.overlay.undo();assert self.data()==before
  self.result['delete_multiple_points_and_undo']='pass'
  self.key(Qt.Key_A,Qt.ControlModifier);assert len(self.c.overlay.selected_point_refs())==9
  self.all_before=self.data();self.c.thickness.setValue(50)
  self.after(lambda:self.wait_update(self.all_done))
 def all_done(self):
  expected=self.data()
  for old,new in zip(self.all_before,expected):
   old0=copy.deepcopy(old);new0=copy.deepcopy(new)
   old0.pop('thickness_profile',None);new0.pop('thickness_profile',None)
   assert old0==new0
  for s in self.c.overlay.strokes:
   for p in s.points:assert math.isclose(s.width*p.thickness,50,abs_tol=1e-8)
  assert len(self.c.overlay.selected_point_refs())==9
  self.result['ctrl_a_sets_same_diameter_above_native_base']='pass'
  self.kra=ROOT/'examples/multi-point.kra';assert self.doc.saveAs(str(self.kra))
  from linework.storage import read_layer
  loaded=self.k.openDocument(str(self.kra));node=loaded.nodeByUniqueID(self.layer.uniqueId())
  assert [s.data() for s in read_layer(loaded,node)]==self.data()
  loaded.setModified(False);loaded.close()
  assert bytes(self.source.pixelData(0,0,self.doc.width(),self.doc.height()))==self.source_before
  self.result['kra_roundtrip_and_raster_source_unchanged']='pass'
  from linework.tools import select_tool
  select_tool(4);self.after(self.capture,300)
 def capture(self):
  options=self.window.qwindow().findChild(QDockWidget,'sharedtooldocker');options.show();options.raise_()
  docks=[d for d in self.window.qwindow().findChildren(QDockWidget) if d.windowTitle()=='Tool Options']
  if docks:self.window.qwindow().resizeDocks(docks,[650]*len(docks),Qt.Vertical)
  QApplication.processEvents()
  self.window.qwindow().grab().save(str(ROOT/'docs/images/multi-point-thickness.png'))
  self.result['result']='pass';self.finish()
Krita.instance().addExtension(Probe(Krita.instance()))
