# SPDX-License-Identifier: GPL-3.0-or-later
"""Static copy action and both native clipboard paths, including .kra reopen."""
import copy,json,os,time,traceback
from pathlib import Path
from krita import Krita,Extension
from linework.qt import QApplication,QTimer,QDialog,QTest,Qt
from linework.animation import AnimationBusy
ROOT=Path(os.environ['LINEWORK_TEST_ROOT']).resolve()
class Probe(Extension):
 def setup(self):self.result={};self.tries=0;self.after(self.start,1800)
 def createActions(self,window):pass
 def after(self,fn,delay=400):QTimer.singleShot(delay,lambda:self.safe(fn))
 def safe(self,fn):
  try:fn()
  except AnimationBusy:self.after(fn,100)
  except Exception:self.result.update(result='fail',traceback=traceback.format_exc());self.finish()
 def start(self):
  self.k=Krita.instance()
  for widget in QApplication.topLevelWidgets():
   if widget.metaObject().className()=='KisAutoSaveRecoveryDialog':QDialog.reject(widget)
  for window in self.k.windows():window.activate();QApplication.setActiveWindow(window.qwindow())
  self.window=self.k.activeWindow()
  if not self.window or not self.window.activeView():
   self.tries+=1;assert self.tries<40;self.after(self.start);return
  self.source=self.k.activeDocument();self.source_view=self.window.activeView()
  from linework.model import Point,Stroke
  from linework.native_brush import capture_brush,NativeBrushRenderer
  from linework.storage import write_layer
  self.source_view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
  if self.source_view.currentBrushPreset() is None:
   self.tries+=1;assert self.tries<40;self.after(self.start);return
  self.k.action('erase_action').setChecked(False)
  strokes=[Stroke([Point(160,180,.6),Point(320,320,.8),Point(550,200,.4)],width=24,brush=copy.deepcopy(capture_brush(self.source_view))),Stroke([Point(200,400),Point(510,430)],width=15,color='#3d7095')]
  renderer=NativeBrushRenderer(self.source_view);self.original=write_layer(self.source,None,strokes,renderer);renderer.close()
  self.initial=[s.data() for s in strokes];self.source_pixels=bytes(self.original.pixelData(0,0,900,900))
  self.k.action('linework_static_copy').trigger();self.after(self.converted)
 def converted(self):
  from linework.storage import read_layer
  from linework.native_brush import active_node,vector_layer
  from linework.animation import record
  self.source.waitForDone();self.layer=vector_layer(active_node(self.source_view))
  assert self.layer.type()=='vectorlayer'
  assert [s.data() for s in read_layer(self.source,self.layer)]==self.initial
  assert [s.data() for s in read_layer(self.source,self.original)]==self.initial
  assert bytes(self.original.pixelData(0,0,900,900))==self.source_pixels
  png=record(self.source,self.original)['appearances'][self.initial[0]['id']]['png']
  assert png in next(s for s in self.layer.shapes() if s.name()=='lw_'+self.initial[0]['id']).toSvg()
  self.result['static_copy_action_keeps_exact_geometry_and_saved_native_png']='pass'
  self.result['static_copy_preserves_source_pixels_and_editability']='pass'
  self.modes=['standard','layers'];self.index=0;self.after(self.copy_layer)
 def copy_layer(self):
  self.mode=self.modes[self.index];self.window.showView(self.source_view);self.source.setActiveNode(self.layer)
  from linework.tools import select_tool
  select_tool(0);self.source.waitForDone()
  if self.mode=='standard':QTest.keyClick(self.window.qwindow(),Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
  else:self.k.action('copy_layer_clipboard').trigger()
  self.after(self.target)
 def target(self):
  assert QApplication.clipboard().mimeData().hasFormat('application/x-krita-linework-layers-v1')
  self.destination=self.k.createDocument(1200,1100,'Static transfer '+self.mode,'RGBA','U8','sRGB-elle-V2-srgbtrc.icc',72)
  self.window.addView(self.destination);self.after(self.paste)
 def paste(self):
  if self.mode=='standard':QTest.keyClick(self.window.qwindow(),Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
  else:self.k.action('paste_layer_from_clipboard').trigger()
  self.deadline=time.monotonic()+10;self.after(self.pasted,700)
 def pasted(self):
  from linework.storage import read_layer
  self.destination.waitForDone();self.node=self.destination.activeNode()
  assert self.node and self.node.type()=='vectorlayer'
  strokes=read_layer(self.destination,self.node)
  if strokes is None:
   assert time.monotonic()<self.deadline;self.after(self.pasted,100);return
  assert [s.data() for s in strokes]==self.initial
  self.result[self.mode+'_native_paste_is_editable_static_linework']='pass'
  self.uid=self.node.uniqueId();self.k.action('edit_undo').trigger();self.after(self.undone)
 def undone(self):
  assert self.uid not in [n.uniqueId() for n in self.destination.rootNode().findChildNodes('',True,False)]
  self.result[self.mode+'_paste_is_one_native_undo_step']='pass'
  self.k.action('edit_redo').trigger();self.after(self.redone)
 def redone(self):
  from linework.storage import read_layer
  self.node=self.destination.nodeByUniqueID(self.uid)
  assert [s.data() for s in read_layer(self.destination,self.node)]==self.initial
  from linework.tools import select_tool,current_controller
  select_tool(3);self.controller=current_controller(self.window);self.controller.poll()
  assert self.controller.overlay and not self.controller._error,self.controller.status.text()
  self.controller.overlay.strokes[0].points[0].x+=10;self.controller.overlay.commit()
  assert not self.controller._error,self.controller.status.text()
  self.edited=[s.data() for s in read_layer(self.destination,self.node)]
  assert self.edited[0]['points'][0][0]==self.initial[0]['points'][0][0]+10
  assert [s.data() for s in read_layer(self.source,self.layer)]==self.initial
  self.result[self.mode+'_pasted_points_edit_independently']='pass'
  path=ROOT/'examples'/('static-transfer-'+self.mode+'.kra');assert self.destination.saveAs(str(path))
  loaded=self.k.openDocument(str(path));assert loaded
  assert [s.data() for s in read_layer(loaded,loaded.nodeByUniqueID(self.uid))]==self.edited
  loaded.setModified(False);loaded.close()
  self.result[self.mode+'_edited_static_copy_reopens_exact']='pass'
  self.index+=1
  if self.index<len(self.modes):self.after(self.copy_layer);return
  self.result.update(result='pass',krita=self.k.version());self.finish()
 def finish(self):
  (ROOT/'docs/validation/static-transfer.json').write_text(json.dumps(self.result,indent=2))
  for doc in self.k.documents():doc.setModified(False)
  self.source=self.source_view=self.original=self.layer=self.controller=self.node=self.destination=None
  if hasattr(self,'window'):self.window.qwindow().close()
  QTimer.singleShot(300,QApplication.instance().quit)
Krita.instance().addExtension(Probe(Krita.instance()))
