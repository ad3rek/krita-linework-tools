# SPDX-License-Identifier: GPL-3.0-or-later
"""Real canvas eraser gestures and topology actions in native Tool Options."""
import copy
import json
import math
import os
import traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QTimer, QEvent, QPointF, Qt
from linework.qt import QMouseEvent, QKeyEvent, tablet_event
from linework.qt import QApplication, QDialog, QDockWidget

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}; self.tries = 0
        self.after(self.start, 1800)
    def createActions(self, window): pass
    def after(self, fn, delay=100): QTimer.singleShot(delay, lambda: self.safe(fn))
    def safe(self, fn):
        try:
            (ROOT/'phase.json').write_text(json.dumps({'phase':fn.__name__, 'completed':self.result}))
            fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc()); self.finish()
    def finish(self):
        (ROOT/'docs/validation/eraser-topology.json').write_text(json.dumps(self.result, indent=2))
        for doc in Krita.instance().documents(): doc.setModified(False)
        if hasattr(self, 'window'): self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)
    def data(self): return [s.data() for s in self.c.overlay.strokes]
    def wait_update(self, fn):
        if self.c._brush_change: self.after(lambda: self.wait_update(fn)); return
        assert self.c.overlay and not self.c._error, self.c.status.text()
        fn()
    def tool(self, mode):
        from linework.tools import select_tool, current_controller
        select_tool(mode); self.c=current_controller(self.window)
        assert self.c is not None
        self.c.poll()
    def mouse(self, kind, x, y, modifiers=Qt.KeyboardModifier.NoModifier):
        self.c._tablet_until = 0
        overlay=self.c.overlay; overlay.sync_transform()
        pos=overlay.image_to_widget.map(QPointF(x,y))
        event=QMouseEvent(kind,pos,Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                         Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,modifiers)
        QApplication.sendEvent(self.c.native_widget,event)
        assert self.c.overlay and not self.c._error, self.c.status.text()
    def click(self,x,y,modifiers=Qt.KeyboardModifier.NoModifier):
        self.mouse(QEvent.Type.MouseButtonPress,x,y,modifiers); self.mouse(QEvent.Type.MouseButtonRelease,x,y,modifiers)
    def key(self,key):
        for kind in (QEvent.Type.ShortcutOverride,QEvent.Type.KeyPress):
            QApplication.sendEvent(self.c.native_widget,QKeyEvent(kind,key,Qt.KeyboardModifier.NoModifier))
    def alpha_column(self,x,y): return sum(bytes(self.layer.projectionPixelData(x,y-20,1,40))[3::4])
    def capture(self,name):
        dock=self.window.qwindow().findChild(QDockWidget,'sharedtooldocker'); dock.show(); dock.raise_()
        self.window.qwindow().resizeDocks([dock],[650],Qt.Orientation.Vertical)
        QApplication.processEvents()
        self.window.qwindow().grab().save(str(ROOT/'docs/images'/name))
    def select(self, keys, primary=None):
        self.c.overlay.selection.set_points(keys)
        if primary is not None: self.c.overlay.selection.primary=primary
        self.c.overlay.selectedChanged.emit(); self.c.overlay.update()
    def assert_saved(self):
        from linework.storage import read_layer
        self.doc.waitForDone()
        assert [s.data() for s in read_layer(self.doc,self.layer)]==self.data()
        assert len(self.layer.shapes())==len(self.c.overlay.strokes)

    def start(self):
        self.k=Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className()=='KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows(): QApplication.setActiveWindow(window.qwindow()); window.activate()
        if not self.k.activeDocument():
            self.tries+=1; assert self.tries<40; self.after(self.start); return
        self.window=self.k.activeWindow(); self.window.qwindow().resize(1450,1020)
        self.view=self.window.activeView(); self.doc=self.view.document(); self.source=self.doc.activeNode()
        self.source_before=bytes(self.source.pixelData(0,0,900,900))
        from linework.tools import select_tool,current_controller
        from linework.model import Point,Stroke
        from linework.native_brush import capture_brush,NativeBrushRenderer
        from linework.storage import write_layer
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.k.action('erase_action').setChecked(False); brush=capture_brush(self.view)
        self.view.setCurrentBrushPreset(self.k.resources('preset')['u) Pixel Art']); pixel=capture_brush(self.view)
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        def row(xs,y,press,width,color,preset,minimum=0):
            points=[Point(x,y,p) for x,p in zip(xs,press)]
            for a,b in zip(points,points[1:]):
                a.handle_out=((b.x-a.x)/3,0); b.handle_in=((a.x-b.x)/3,0)
            return Stroke(points,width=width,color=color,brush=copy.deepcopy(preset),minimum=minimum)
        strokes=[row([120,270,420],140,[.3,.7,.8],12,'#bd2834',brush,.2),
                 row([480,600,750],260,[.8,.3,.6],24,'#2754be',pixel),
                 Stroke([Point(270,400)],width=20,color='#378041'),
                 row([120,270,420],520,[.5,.8,1],16,'#7d3da1',None),
                 row([120,200,280,360,440],640,[1]*5,20,'#be6e16',None),
                 Stroke([Point(550,500,.5),Point(650,580,.8),Point(750,520,.7)],width=18,color='#277d88',brush=copy.deepcopy(brush))]
        for p,w in zip(strokes[1].points,[.9,.6,1.2]): p.thickness=w
        select_tool(3); self.c=current_controller(self.window); self.layer=self.c.create_native_layer(self.doc, 'vectorlayer')
        renderer=NativeBrushRenderer(self.view); write_layer(self.doc,self.layer,strokes,renderer); renderer.close()
        self.ids=[s.uid for s in strokes]; self.initial=[s.data() for s in strokes]
        self.after(self.partial_erase,300)

    def partial_erase(self):
        self.tool(5); assert self.c.eraser_group.isVisible() and not self.c.topology_group.isVisible()
        self.c.eraser_mode.setCurrentIndex(1); self.c.eraser_size.setValue(64); self.c.eraser_strength.setValue(50)
        self.before=self.data(); self.depth=len(self.c.overlay.history.undo_stack)
        self.original_alpha=self.alpha_column(270,140)
        self.click(270,140); self.after(self.partial_checked,250)
    def partial_checked(self):
        from linework.native_brush import point_thickness,size_factor
        stroke=self.c.overlay.strokes[0]; original=self.before[0]
        baseline=original['width']*(.2+.8*size_factor(original['brush'],.7))
        assert math.isclose(point_thickness(stroke,1),baseline*.5,abs_tol=1e-7)
        assert stroke.data()['points']==original['points'] and stroke.data()['handles']==original['handles']
        assert stroke.minimum==0
        assert self.alpha_column(270,140)<self.original_alpha,(self.alpha_column(270,140),self.original_alpha)
        assert len(self.c.overlay.history.undo_stack)==self.depth+1
        self.partial=self.data(); self.c.overlay.undo(); assert self.data()==self.before
        self.c.overlay.redo(); assert self.data()==self.partial
        self.assert_saved(); self.capture('eraser-points.png')
        self.result['point_eraser_reduces_native_pixels_and_diameter_preserves_geometry_pressure_and_undo']='pass'
        self.c.eraser_strength.setValue(100); self.click(270,140); self.after(self.zero_and_cancel,250)
    def zero_and_cancel(self):
        assert self.c.overlay.strokes[0].points[1].thickness==0
        assert len(self.c.overlay.strokes[0].points)==3
        self.assert_saved(); self.result['zero_width_keeps_editable_anchor']='pass'
        self.before=self.data(); self.depth=len(self.c.overlay.history.undo_stack)
        self.mouse(QEvent.Type.MouseButtonPress,420,140); self.mouse(QEvent.Type.MouseMove,480,260)
        self.key(Qt.Key.Key_Escape)
        assert self.data()==self.before and len(self.c.overlay.history.undo_stack)==self.depth
        assert self.c.overlay._edit_original is None
        self.result['point_eraser_escape_restores_originals']='pass'
        self.click(270,400); self.after(self.zero_dot,200)
    def zero_dot(self):
        assert self.c.overlay.strokes[2].points[0].thickness==0
        self.assert_saved()
        self.tool(4); self.select({(self.ids[2],0)})
        self.c.thickness.setValue(18); self.after(lambda:self.wait_update(self.recovered_dot),150)
    def recovered_dot(self):
        assert self.alpha_column(270,400)>0
        self.assert_saved(); self.result['fully_erased_smooth_dot_remains_editable_and_can_be_restored']='pass'
        self.tool(5); self.c.eraser_mode.setCurrentIndex(1); self.c.eraser_strength.setValue(100)
        self.before=self.data(); self.depth=len(self.c.overlay.history.undo_stack)
        self.c.overlay.sync_transform(); pos=self.c.overlay.image_to_widget.map(QPointF(270,400))
        for kind in [QEvent.Type.TabletPress]+[QEvent.Type.TabletMove]*20+[QEvent.Type.TabletRelease]:
            event=tablet_event(kind,pos,0 if kind==QEvent.Type.TabletRelease else .25,
                Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton if kind==QEvent.Type.TabletRelease else Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.c.native_widget,event)
        self.after(self.pressure_checked,200)
    def pressure_checked(self):
        from linework.native_brush import point_thickness
        assert math.isclose(point_thickness(self.c.overlay.strokes[2],0),13.5,abs_tol=1e-7)
        assert self.c.overlay.strokes[2].points[0].pressure==1
        assert len(self.c.overlay.history.undo_stack)==self.depth+1
        self.c.overlay.undo(); assert self.data()==self.before
        self.result['tablet_pressure_and_repeated_stationary_samples_control_eraser_without_buildup']='pass'
        self.mouse(QEvent.Type.MouseButtonPress,270,520)
        assert self.c.overlay._edit_original
        path=ROOT/'examples/save-during-erase.kra'; assert self.doc.saveAs(str(path))
        assert self.c.overlay._edit_original is None and self.c.overlay._edit_session is None
        assert self.c.overlay.strokes[3].points[1].thickness==0
        self.assert_saved(); self.c.overlay.undo(); assert self.data()==self.before
        self.result['saving_during_eraser_gesture_finishes_once_and_keeps_editable_data']='pass'
        self.tool(5); self.c.eraser_mode.setCurrentIndex(0); self.c.eraser_size.setValue(30)
        before=self.data(); depth=len(self.c.overlay.history.undo_stack)
        self.mouse(QEvent.Type.MouseButtonPress,850,850); self.c.overlay.undo()
        self.mouse(QEvent.Type.MouseButtonRelease,850,850)
        assert self.data()==before and len(self.c.overlay.history.undo_stack)==depth
        self.result['undo_empty_eraser_gesture_does_not_undo_previous_edit']='pass'
        self.before=self.data(); self.depth=len(self.c.overlay.history.undo_stack)
        self.mouse(QEvent.Type.MouseButtonPress,270,520); self.mouse(QEvent.Type.MouseMove,270,640)
        assert len(self.c.overlay.strokes)==4 and len(self.layer.shapes())==6
        self.key(Qt.Key.Key_Escape)
        assert self.data()==self.before and len(self.c.overlay.history.undo_stack)==self.depth
        self.assert_saved(); self.result['whole_line_eraser_preview_hides_originals_and_escape_restores_order']='pass'
        self.mouse(QEvent.Type.MouseButtonPress,270,490); self.mouse(QEvent.Type.MouseMove,270,660)
        self.mouse(QEvent.Type.MouseButtonRelease,270,660); self.after(self.lines_deleted,200)
    def lines_deleted(self):
        assert len(self.c.overlay.strokes)==4 and len(self.layer.shapes())==4
        assert len(self.c.overlay.history.undo_stack)==self.depth+1
        assert not {self.ids[3],self.ids[4]} & {s.uid for s in self.c.overlay.strokes}
        self.c.overlay.undo(); assert self.data()==self.before
        self.c.overlay.redo(); assert len(self.c.overlay.strokes)==4
        self.c.overlay.undo(); self.assert_saved()
        self.result['fast_swept_line_eraser_deletes_multiple_strokes_in_one_undo']='pass'
        self.layer.setLocked(True); before=self.data(); self.click(270,140)
        assert self.data()==before and self.c.overlay and not self.c._error
        self.layer.setLocked(False); self.result['locked_layer_preserved_without_disabling_editor']='pass'
        self.tool(3); assert self.c.topology_group.isVisible() and not self.c.eraser_group.isVisible()
        # Real Shift-click selects two different endpoints. Last click is active.
        self.click(420,140); self.click(480,260,Qt.KeyboardModifier.ShiftModifier)
        assert self.c.overlay.selection.primary==(self.ids[1],0)
        assert self.c.join_button.isEnabled()
        self.before=self.data(); self.depth=len(self.c.overlay.history.undo_stack)
        self.c.join_button.click(); self.after(lambda:self.wait_update(self.joined),150)
    def joined(self):
        from linework.native_brush import point_thickness
        assert len(self.c.overlay.strokes)==5
        joined=next(s for s in self.c.overlay.strokes if s.uid==self.ids[1])
        a,b=self.before[:2]
        assert joined.color==b['color'] and joined.brush==b['brush'] and joined.width==b['width']
        assert len(joined.points)==6 and len(self.c.overlay.history.undo_stack)==self.depth+1
        expected=[p[2] for p in reversed(b['points'])]+[p[2] for p in reversed(a['points'])]
        assert [p.pressure for p in joined.points]==expected
        expected_widths=[b['width']*p[0] for p in reversed(b['thickness_profile'])]+[a['width']*p[0] for p in reversed(a['thickness_profile'])]
        assert all(math.isclose(point_thickness(joined,i),w,abs_tol=1e-7) for i,w in enumerate(expected_widths))
        self.assert_saved(); self.joined_data=self.data()
        self.c.overlay.undo(); assert self.data()==self.before
        self.c.overlay.redo(); assert self.data()==self.joined_data
        self.c.overlay.undo()
        self.result['join_real_shift_selection_preserves_active_style_all_diameters_pressure_and_history']='pass'
        self.select({(self.ids[4],1),(self.ids[4],2)},(self.ids[4],2))
        self.c.merge_position.setCurrentIndex(0); self.before=self.data()
        self.c.merge_button.click(); self.c.cancel_brush_button.click(); assert self.data()==self.before
        self.result['topology_cancellation_preserves_data']='pass'
        self.c.merge_button.click(); self.after(lambda:self.wait_update(self.merged_center),150)
    def merged_center(self):
        stroke=next(s for s in self.c.overlay.strokes if s.uid==self.ids[4])
        assert len(stroke.points)==4 and math.isclose(stroke.points[1].x,240)
        self.assert_saved(); self.c.overlay.undo(); assert self.data()==self.before
        self.select({(self.ids[4],1),(self.ids[4],2)},(self.ids[4],2))
        self.c.merge_position.setCurrentIndex(1); self.c.merge_button.click()
        self.after(lambda:self.wait_update(self.merged_active),150)
    def merged_active(self):
        stroke=next(s for s in self.c.overlay.strokes if s.uid==self.ids[4])
        assert len(stroke.points)==4 and math.isclose(stroke.points[1].x,280)
        self.assert_saved(); self.result['consecutive_points_merge_at_center_or_active']='pass'
        self.select({(self.ids[0],2),(self.ids[1],0)},(self.ids[1],0))
        self.c.merge_button.click(); self.after(lambda:self.wait_update(self.welded),150)
    def welded(self):
        stroke=next(s for s in self.c.overlay.strokes if s.uid==self.ids[1])
        assert len(self.c.overlay.strokes)==5 and len(stroke.points)==5
        assert math.isclose(stroke.points[2].x,480) and math.isclose(stroke.points[2].y,260)
        assert stroke.brush==self.before[1]['brush'] and stroke.color==self.before[1]['color']
        self.assert_saved(); self.result['merge_two_endpoints_welds_at_active_point']='pass'
        self.select({(self.ids[5],0),(self.ids[5],2)},(self.ids[5],2))
        assert not self.c.merge_button.isEnabled() and self.c.join_button.isEnabled()
        self.c.join_button.click(); self.after(lambda:self.wait_update(self.closed),150)
    def closed(self):
        stroke=next(s for s in self.c.overlay.strokes if s.uid==self.ids[5])
        assert len(stroke.points)==4 and (stroke.points[0].x,stroke.points[0].y)==(stroke.points[-1].x,stroke.points[-1].y)
        self.assert_saved(); self.result['joining_same_stroke_endpoints_closes_curve']='pass'
        before=self.data(); self.layer.setLocked(True)
        self.c.topology_action('merge'); assert self.data()==before
        self.layer.setLocked(False); self.result['locked_topology_operation_preserves_model']='pass'
        path=ROOT/'examples/eraser-topology.kra'; assert self.doc.saveAs(str(path))
        self.expected=self.data(); self.loaded=self.k.openDocument(str(path))
        self.loaded_layer=self.loaded.nodeByUniqueID(self.layer.uniqueId())
        self.window.addView(self.loaded); self.loaded.refreshProjection(); self.after(self.reopened,500)
    def reopened(self):
        from linework.storage import read_layer
        self.loaded.waitForDone()
        assert [s.data() for s in read_layer(self.loaded,self.loaded_layer)]==self.expected
        assert sum(bytes(self.loaded_layer.projectionPixelData(270,380,1,40))[3::4])>0
        assert bytes(self.source.pixelData(0,0,900,900))==self.source_before
        self.tool(3); self.select({(self.ids[1],2)},(self.ids[1],2))
        self.result['kra_roundtrip_rendered_pixels_and_original_bitmap_preserved']='pass'
        self.selection_checks()
        self.capture('merge-join-tools.png')
        self.result.update(result='pass',krita=self.k.version()); self.finish()

    def selection_checks(self):
        from linework.model import handle_vector
        o=self.c.overlay; before=self.data(); stroke=next(s for s in o.strokes if s.uid==self.ids[1]); index=2
        anchor=stroke.points[index]; o.sync_transform()
        # A screen-space miss outside the former 10 px anchor target now hits.
        self.c.selection_mode.setCurrentIndex(1)
        self.click(anchor.x,anchor.y+13/o.zoom)
        assert o.selection.points=={(stroke.uid,index)}
        self.result['expanded_anchor_hit_radius_in_screen_pixels']='pass'
        side,vector=next((side,handle_vector(stroke,index,side)) for side in ('in','out') if math.hypot(*(handle_vector(stroke,index,side) or (0,0)))>40/o.zoom)
        length=math.hypot(*vector)
        x=anchor.x+vector[0]-vector[1]/length*12/o.zoom
        y=anchor.y+vector[1]+vector[0]/length*12/o.zoom
        self.mouse(QEvent.Type.MouseButtonPress,x,y)
        assert o.drag=='handle' and o.handle_side==side
        self.key(Qt.Key.Key_Escape); assert self.data()==before
        self.result['expanded_handle_hit_radius_escape_preserves_geometry']='pass'
        self.c.lock_point.setChecked(True); assert o.locked_point==(stroke.uid,index)
        self.click(120,640); self.click(750,260,Qt.KeyboardModifier.ShiftModifier)
        o.select_all(); assert o.selection.points=={(stroke.uid,index)} and not o.selection.strokes
        self.tool(4); assert self.c.overlay.locked_point==(stroke.uid,index)
        self.click(750,260); assert self.c.overlay.selection.points=={(stroke.uid,index)}
        self.tool(3); o=self.c.overlay
        self.mouse(QEvent.Type.MouseButtonPress,anchor.x,anchor.y)
        self.mouse(QEvent.Type.MouseMove,anchor.x+15,anchor.y+5)
        assert o.drag=='point' and self.data()!=before
        self.key(Qt.Key.Key_Escape); assert self.data()==before
        self.result['locked_active_point_ignores_misses_shift_select_all_and_survives_tool_switch']='pass'
        self.c.lock_point.setChecked(False)
        self.c.selection_mode.setCurrentIndex(2)
        self.click(anchor.x,anchor.y)
        assert o.selection.strokes=={stroke.uid} and not o.selection.points
        assert len(o.selected_point_refs())==len(stroke.points)
        self.mouse(QEvent.Type.MouseButtonPress,anchor.x,anchor.y)
        self.mouse(QEvent.Type.MouseMove,anchor.x+15,anchor.y+5)
        assert o.drag=='stroke'
        for old,new in zip(before,self.data()):
            if old['id']==stroke.uid:
                assert all(math.isclose(p[0]-q[0],15,abs_tol=1e-5) and math.isclose(p[1]-q[1],5,abs_tol=1e-5) for p,q in zip(new['points'],old['points']))
            else: assert old==new
        self.key(Qt.Key.Key_Escape); assert self.data()==before
        self.result['stroke_selection_from_anchor_moves_whole_path_and_escape_restores']='pass'
        self.c.selection_mode.setCurrentIndex(1); self.select({(stroke.uid,index)},(stroke.uid,index))


Krita.instance().addExtension(Probe(Krita.instance()))
