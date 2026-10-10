# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise editable geometry through actual Krita raster keyframes and Undo."""
import copy
import json
import os
import traceback
import zipfile
from pathlib import Path
from krita import Krita, Extension, ManagedColor, InfoObject
from linework.qt import QTimer, Qt, QEventLoop, QEvent, QPointF
from linework.qt import QColor, QKeyEvent, QMouseEvent, QImage
from linework.qt import QApplication, QDialog, QDockWidget, QTableView

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}; self.tries = 0
        self.after(self.start, 1800)
    def createActions(self, window): pass
    def after(self, fn, delay=100): QTimer.singleShot(delay, lambda: self.safe(fn))
    def safe(self, fn):
        try:
            if hasattr(self,'c') and (self.c.input_busy() or self.c._pending_input):
                self.after(fn,100); return
            (ROOT/'phase.json').write_text(json.dumps({'phase':fn.__name__, 'completed':self.result}))
            fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc()); self.finish()
    def finish(self):
        from linework.native_brush import native_busy
        if native_busy() or (hasattr(self,'c') and self.c.input_busy()):
            self.after(self.finish,100); return
        (ROOT/'docs/validation/animation.json').write_text(json.dumps(self.result, indent=2))
        for doc in Krita.instance().documents(): doc.setModified(False)
        # libkis Node wrappers keep images alive. Release the probe's handles
        # while native views/tools still exist, before closing their window.
        self.original=self.layer=self.view=self.doc=None
        if hasattr(self, 'window'): self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)
    def state(self):
        from linework.animation import call
        self.doc.waitForDone()
        return call('info', self.layer, 1)
    def geometry(self, time):
        from linework.animation import record
        frame=next(f for f in self.state()['frames'] if f['time']==time)
        return record(self.doc,self.layer,frame)['strokes']
    def seek(self, time):
        self.doc.setCurrentTime(time); self.doc.waitForDone()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        self.c.poll()
        assert self.c.overlay and not self.c._error, self.c.status.text()
    def edit_width(self, width):
        self.c.overlay.strokes[0].width=width
        self.c.overlay.commit()
        self.doc.waitForDone(); self.c.poll()
        assert self.c.overlay and not self.c._error, self.c.status.text()
    def native_action(self, action, source, target):
        from linework.animation import call
        call('frame_action',self.layer,action,source,target)
        self.doc.waitForDone()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    def undo(self, redo=False):
        action=self.k.action('edit_redo' if redo else 'edit_undo')
        assert action and action.isEnabled()
        action.trigger(); self.doc.waitForDone()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        self.doc.waitForDone(); self.c.poll()
    def pointer(self, kind, x, y):
        self.c._tablet_until=0
        o=self.c.overlay; o.sync_transform()
        pos=o.image_to_widget.map(QPointF(x,y))
        event=QMouseEvent(kind,pos,Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.c.native_widget,event)
        assert self.c.overlay and not self.c._error,self.c.status.text()
    def key(self,key):
        for kind in (QEvent.Type.ShortcutOverride,QEvent.Type.KeyPress):
            QApplication.sendEvent(self.c.native_widget,QKeyEvent(kind,key,Qt.KeyboardModifier.NoModifier))
    def pixels(self):
        self.doc.waitForDone()
        return bytes(self.layer.pixelData(0,0,self.doc.width(),self.doc.height()))
    def wait_update(self,fn):
        if self.c._brush_change or self.c._pending_color or self.c.color_timer.isActive():
            self.after(lambda:self.wait_update(fn)); return
        assert self.c.overlay and not self.c._error,self.c.status.text()
        fn()
    def start(self):
        self.k=Krita.instance()
        QApplication.instance().setQuitOnLastWindowClosed(False)
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className()=='KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows(): QApplication.setActiveWindow(window.qwindow()); window.activate()
        if not self.k.activeDocument():
            self.tries+=1; assert self.tries<40; self.after(self.start); return
        self.window=self.k.activeWindow(); self.window.qwindow().resize(1450,1020)
        self.view=self.window.activeView(); self.doc=self.view.document()
        from linework.tools import select_tool,current_controller
        from linework.model import Point,Stroke
        from linework.native_brush import capture_brush,NativeBrushRenderer
        from linework.storage import write_layer
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.k.action('erase_action').setChecked(False); brush=capture_brush(self.view)
        strokes=[Stroke([Point(120,180,.7),Point(280,260,.8),Point(460,140,.6)],width=18,color='#202020',brush=copy.deepcopy(brush)),
                 Stroke([Point(130,430),Point(500,430)],width=12,color='#2c75c6')]
        self.initial=[s.data() for s in strokes]
        select_tool(3); self.c=current_controller(self.window)
        self.original=self.c.create_native_layer(self.doc)
        renderer=NativeBrushRenderer(self.view)
        write_layer(self.doc,self.original,strokes,renderer); renderer.close()
        self.doc.waitForDone(); self.c.poll()
        self.after(self.convert_layer,300)
    def convert_layer(self):
        self.c.animate_layer()
        self.after(self.converted_layer,300)
    def converted_layer(self):
        self.c.poll()
        self.layer=self.c.layer
        assert self.layer and self.layer.type()=='paintlayer', {
            'status':self.c.status.text(),'error':self.c._error,
            'active_node':self.doc.activeNode().type() if self.doc.activeNode() else None,
            'layer':self.layer.type() if self.layer else None,
            'controller_mode':self.c.mode}
        self.after(self.initialized,300)
    def initialized(self):
        assert not self.original.visible()
        assert self.geometry(0)==self.initial
        from linework.storage import read_layer,metadata
        assert [s.data() for s in read_layer(self.doc,self.layer)]==self.initial
        assert metadata(self.doc)['version']==7
        self.result['conversion_preserves_geometry_and_source_backup']='pass'
        self.native_action(2,0,5)
        assert self.geometry(5)==self.initial
        self.seek(5); self.edit_width(30)
        self.changed=self.geometry(5)
        assert self.changed[0]['width']==30 and self.geometry(0)==self.initial
        self.result['native_timeline_copy_keeps_geometry_and_edits_independent']='pass'
        self.undo(); assert self.geometry(5)==self.initial
        self.undo(True); assert self.geometry(5)==self.changed
        self.result['native_geometry_and_raster_undo_redo']='pass'
        self.native_action(3,5,8)
        assert self.geometry(8)==self.changed and 5 not in [f['time'] for f in self.state()['frames']]
        self.native_action(4,8,0)
        assert 8 not in [f['time'] for f in self.state()['frames']]
        self.undo(); assert self.geometry(8)==self.changed
        self.result['native_move_delete_and_undo_keep_geometry']='pass'
        self.native_action(5,0,12)
        self.seek(0); self.edit_width(22)
        assert self.geometry(0)==self.geometry(12)
        assert self.geometry(8)==self.changed
        self.result['linked_clone_frames_stay_linked']='pass'
        self.native_action(1,0,3)
        self.seek(3)
        assert not self.c.overlay.strokes
        from linework.storage import read_layer
        assert read_layer(self.doc,self.layer)==[]
        self.result['native_blank_frame_is_editable']='pass'
        self.after(self.canvas_draw,200)
    def canvas_draw(self):
        from linework.tools import select_tool
        self.others={time:self.geometry(time) for time in (0,8,12)}
        select_tool(0); self.c.poll()
        self.view.setBrushSize(16); self.view.setPaintingOpacity(1)
        self.pointer(QEvent.Type.MouseButtonPress,160,650)
        for x in range(170,501,10): self.pointer(QEvent.Type.MouseMove,x,650)
        self.pointer(QEvent.Type.MouseButtonRelease,500,650)
        self.after(self.canvas_drawn,200)
    def canvas_drawn(self):
        self.doc.waitForDone(); self.c.poll()
        self.drawn=self.geometry(3)
        assert len(self.drawn)==1 and sum(bytes(self.layer.pixelData(220,640,80,20))[3::4])>1000
        for time,data in self.others.items(): assert self.geometry(time)==data
        self.result['canvas_brush_on_blank_frame_preserves_other_frames']='pass'
        self.undo(); assert self.geometry(3)==[]
        self.undo()  # Krita records timeline seeking as its own native Undo.
        self.undo(); assert 3 not in [f['time'] for f in self.state()['frames']]
        self.undo(True); assert self.geometry(3)==[]
        self.undo(True)
        self.undo(True); assert self.geometry(3)==self.drawn
        self.result['blank_creation_and_brush_edit_undo_redo_sequence']='pass'
        from linework.tools import select_tool
        select_tool(3); self.seek(0)
        self.before_edit=self.geometry(0); self.before_pixels=self.pixels()
        self.unselected_pixels=bytes(self.layer.pixelData(130,420,370,20))
        self.pointer(QEvent.Type.MouseButtonPress,120,180)
        assert self.c.overlay.drag=='point' and self.c.overlay._raster_preview
        assert sum(bytes(self.layer.pixelData(105,165,30,30))[3::4])==0
        assert bytes(self.layer.pixelData(130,420,370,20))==self.unselected_pixels
        self.pointer(QEvent.Type.MouseMove,160,210)
        self.key(Qt.Key.Key_Escape)
        assert self.geometry(0)==self.before_edit and self.pixels()==self.before_pixels
        self.result['point_preview_hides_original_and_cancel_restores_exact_pixels']='pass'
        self.pointer(QEvent.Type.MouseButtonPress,120,180)
        self.pointer(QEvent.Type.MouseMove,160,210)
        self.seek(8); assert self.geometry(0)==self.before_edit and self.geometry(8)==self.others[8]
        self.seek(0); assert self.pixels()==self.before_pixels
        self.result['timeline_switch_during_drag_restores_captured_frame']='pass'
        self.pointer(QEvent.Type.MouseButtonPress,120,180)
        self.pointer(QEvent.Type.MouseMove,160,210)
        assert self.doc.saveAs(str(ROOT/'examples/animation-during-point-preview.kra'))
        assert not self.c.overlay._raster_preview and self.geometry(0)==self.before_edit
        assert self.pixels()==self.before_pixels
        self.result['saving_during_point_preview_restores_confirmed_frame']='pass'
        self.pointer(QEvent.Type.MouseButtonPress,120,180)
        self.pointer(QEvent.Type.MouseMove,160,210)
        self.pointer(QEvent.Type.MouseButtonRelease,160,210)
        assert self.geometry(0)!=self.before_edit and self.geometry(8)==self.others[8]
        self.undo(); self.seek(0); assert self.geometry(0)==self.before_edit and self.pixels()==self.before_pixels
        self.undo(True); self.seek(0)
        self.result['point_release_commits_geometry_and_native_pixels_together']='pass'
        self.c.overlay.select_all(); self.c.thickness.setValue(14)
        self.after(lambda:self.wait_update(self.thickness_done))
    def thickness_done(self):
        for s in self.c.overlay.strokes:
            for p in s.points: assert abs(s.width*p.thickness-14)<1e-6
        assert self.geometry(8)==self.others[8]
        self.result['multiple_point_thickness_is_frame_local']='pass'
        self.view.setForeGroundColor(ManagedColor.fromQColor(QColor('#d92437'),self.view.canvas()))
        self.c.poll(); self.after(lambda:self.wait_update(self.color_done),550)
    def color_done(self):
        assert all(s.color=='#d92437' for s in self.c.overlay.strokes)
        assert self.geometry(8)==self.others[8]
        self.result['foreground_color_is_frame_local']='pass'
        self.view.setCurrentBrushPreset(self.k.resources('preset')['u) Pixel Art'])
        self.after(self.replace_brush,150)
    def replace_brush(self):
        self.c.apply_current_brush(); self.after(lambda:self.wait_update(self.brush_done))
    def brush_done(self):
        assert all(s.brush and s.brush['name']=='u) Pixel Art' for s in self.c.overlay.strokes), {
            'brushes':[s.brush['name'] if s.brush else None for s in self.c.overlay.strokes],
            'selection':list(self.c.overlay.selection.ids()),'status':self.c.status.text()}
        assert self.geometry(8)==self.others[8]
        self.result['native_brush_replacement_is_frame_local']='pass'
        from linework.tools import select_tool
        self.before_erase=self.geometry(0)
        select_tool(5); self.c.poll(); self.view.setBrushSize(32)
        self.pointer(QEvent.Type.MouseButtonPress,400,430)
        self.pointer(QEvent.Type.MouseButtonRelease,400,430)
        assert len(self.geometry(0))==1 and self.geometry(8)==self.others[8]
        self.undo(); self.seek(0); assert self.geometry(0)==self.before_erase
        self.result['line_eraser_and_native_undo_are_frame_local']='pass'
        self.c.eraser_mode.setCurrentIndex(1)
        self.pointer(QEvent.Type.MouseButtonPress,160,210)
        self.pointer(QEvent.Type.MouseButtonRelease,160,210)
        assert self.geometry(0)!=self.before_erase and self.geometry(8)==self.others[8]
        self.undo(); self.seek(0); assert self.geometry(0)==self.before_erase
        self.result['point_thinning_and_native_undo_are_frame_local']='pass'
        select_tool(3); self.c.poll()
        from linework.model import Point,Stroke
        self.native_action(1,0,20); self.seek(20)
        self.c.overlay.strokes=[Stroke([Point(100,100),Point(200,100)],opacity=0)]
        self.c.overlay.commit(); self.doc.waitForDone(); self.c.poll()
        self.native_action(2,20,21); self.seek(21)
        self.c.overlay.strokes[0].points[0].x=300
        self.c.overlay.commit(); self.doc.waitForDone(); self.c.poll()
        assert self.geometry(20)!=self.geometry(21)
        first=next(f['payload']['fingerprint'] for f in self.state()['frames'] if f['time']==20)
        second=next(f['payload']['fingerprint'] for f in self.state()['frames'] if f['time']==21)
        assert first==second
        self.native_action(2,21,22); assert self.geometry(22)==self.geometry(21)
        self.result['identical_raster_frames_keep_distinct_geometry_when_copied']='pass'
        self.seek(8)
        from linework.animation import call
        call('frame_action',self.layer,2,22,23)  # Do not drain the queued metadata callback.
        self.path=ROOT/'examples/linework-animation.kra'
        assert self.doc.saveAs(str(self.path)); self.doc.waitForDone()
        with zipfile.ZipFile(self.path) as archive:
            data=json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('/annotations/org.felipe.linework.v1'))))
        from linework.storage import layer_id
        assert data['layers'][layer_id(self.layer)]['frames']['23']['strokes']==self.geometry(21)
        self.result['save_immediately_after_native_copy_includes_geometry']='pass'
        self.saved={f['time']:f['payload']['strokes'] for f in self.state()['frames']}
        self.after(self.reopen,200)
    def reopen(self):
        reopened=self.k.openDocument(str(self.path))
        assert reopened
        self.window.addView(reopened); QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        self.doc=reopened; self.view=self.window.activeView()
        # Adding a view schedules projection work. Identify the saved layer
        # without asking the native frame API to read pixels during that work.
        from linework.storage import metadata,layer_id
        saved=metadata(reopened)['layers']
        self.layer=next(n for n in reopened.rootNode().findChildNodes('',True,False,'paintlayer')
                        if saved.get(layer_id(n),{}).get('kind')=='animated')
        self.reopen_tries=0
        self.after(self.bind_reopened,300)
    def bind_reopened(self):
        from linework.tools import select_tool,current_controller
        from linework.animation import record,AnimationBusy
        self.doc.waitForDone()
        try:
            assert record(self.doc,self.layer) is not None
        except AnimationBusy:
            self.reopen_tries+=1
            assert self.reopen_tries<40, 'Reopened animation did not become idle'
            self.after(self.bind_reopened,100); return
        self.doc.setActiveNode(self.layer); select_tool(3); self.c=current_controller(self.window)
        self.after(self.reopened_checked,300)
    def reopened_checked(self):
        self.c.poll()
        for time,data in self.saved.items(): assert self.geometry(time)==data,(time,self.state())
        self.seek(8); self.edit_width(37)
        assert self.geometry(8)[0]['width']==37
        self.result['kra_reopen_and_edit_multiple_frames']='pass'
        self.native_action(2,23,24); assert self.geometry(24)==self.saved[23]
        self.result['copy_after_kra_reopen_keeps_identical_raster_geometry']='pass'
        from linework.animation import call
        from linework.storage import read_layer,write_layer,layer_id
        call('frame_action',self.layer,2,24,25)
        backup=self.doc.nodeByUniqueID(self.original.uniqueId())
        vectors=read_layer(self.doc,backup); vectors[1].width+=1
        write_layer(self.doc,backup,vectors)
        mixed=ROOT/'examples/animation-after-vector-edit.kra'
        assert self.doc.saveAs(str(mixed))
        with zipfile.ZipFile(mixed) as archive:
            data=json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('/annotations/org.felipe.linework.v1'))))
        assert data['layers'][layer_id(self.layer)]['frames']['25']['strokes']==self.saved[23]
        self.result['vector_commit_keeps_native_animation_save_snapshot']='pass'
        self.doc.setActiveNode(self.layer); self.c.poll()
        for time in (0,3,8):
            self.seek(time)
            path=ROOT/'examples'/('animation-frame-'+str(time)+'.png')
            # Use Krita's guarded save/export snapshot path. libkis clone() and
            # synchronous exportImage() expect an externally locked document.
            self.doc.setBatchmode(True)
            assert self.doc.saveAs(str(path)),(time,'Native PNG save returned false')
            self.doc.setBatchmode(False)
            image=QImage(str(path)); assert not image.isNull() and image.size().width()==900
            pixel=image.pixelColor(300,650 if time==3 else 430)
            assert pixel.alpha()>0,(time,pixel.name())
            if time==0: assert pixel.red()>pixel.blue()
            if time==8: assert pixel.blue()>pixel.red()
        self.result['native_png_frame_exports']='pass'
        self.doc.setFullClipRangeStartTime(0); self.doc.setFullClipRangeEndTime(12)
        self.doc.setFramesPerSecond(6)
        self.seek(8)
        for dock in self.window.qwindow().findChildren(QDockWidget):
            if 'timeline' in dock.objectName().lower(): dock.show()
        self.after(self.timeline_copy,200)
    def timeline_select(self,time):
        table=next(w for w in self.window.qwindow().findChildren(QTableView)
                   if w.metaObject().className()=='KisAnimTimelineFramesView')
        model=table.model()
        row=next(r for r in range(model.rowCount()) if model.index(r,0).data(Qt.ItemDataRole.DisplayRole)==self.layer.name())
        index=model.index(row,time); table.scrollTo(index)
        pos=QPointF(table.visualRect(index).center())
        for kind in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease):
            buttons=Qt.MouseButton.LeftButton if kind==QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton
            QApplication.sendEvent(table.viewport(),QMouseEvent(kind,pos,Qt.MouseButton.LeftButton,buttons,Qt.KeyboardModifier.NoModifier))
        self.doc.waitForDone(); QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    def timeline_copy(self):
        self.timeline_select(26)
        action=self.k.action('add_duplicate_frame'); assert action and action.isEnabled()
        action.trigger(); self.doc.waitForDone()
        self.after(self.timeline_copied,200)
    def timeline_copied(self):
        assert self.geometry(26)==self.saved[23]
        self.result['real_timeline_cell_and_duplicate_action_keep_geometry']='pass'
        self.seek(8); self.k.action('toggle_playback').trigger(); self.after(self.playing,450)
    def playing(self):
        from linework.animation import playback
        assert playback(self.view)
        self.c.poll(); assert not self.c.overlay.isVisible()
        playback(self.view,True); self.doc.waitForDone(); self.c.poll()
        assert self.c.overlay.isVisible()
        self.result['native_playback_hides_edit_overlay_and_pause_restores_it']='pass'
        self.seek(8); self.c.overlay.select_all()
        dock=self.window.qwindow().findChild(QDockWidget,'sharedtooldocker')
        if dock: dock.show(); dock.raise_()
        self.k.action('toggle_onion_skin').trigger()
        self.after(self.capture,300)
    def capture(self):
        self.doc.waitForDone()
        assert self.doc.saveAs(str(self.path))
        self.window.qwindow().grab().save(str(ROOT/'docs/images/animation-in-krita.png'))
        self.after(self.before_first,100)
    def before_first(self):
        from linework.tools import select_tool
        self.old_zero=self.geometry(0)
        self.native_action(3,0,30); self.seek(0)
        # Krita always regenerates a native blank at 0 when that key is moved.
        assert not self.c.overlay.strokes and self.geometry(0)==[]
        select_tool(0); self.c.poll()
        self.pointer(QEvent.Type.MouseButtonPress,100,100)
        self.pointer(QEvent.Type.MouseMove,300,100)
        self.pointer(QEvent.Type.MouseButtonRelease,300,100)
        self.after(self.before_first_checked,100)
    def before_first_checked(self):
        assert len(self.geometry(0))==1 and self.geometry(30)==self.old_zero
        self.result['drawing_on_regenerated_zero_frame_keeps_moved_geometry']='pass'
        self.c.overlay.sync_transform()
        canvas=self.c.native_widget; transform=self.c.overlay.image_to_widget
        self.external_before=bytes(self.layer.projectionPixelData(760,760,100,100))
        action=self.k.action('KritaShape/KisToolBrush'); assert action
        action.trigger()
        for kind,x in [(QEvent.Type.MouseButtonPress,800),(QEvent.Type.MouseMove,815),(QEvent.Type.MouseButtonRelease,815)]:
            pos=transform.map(QPointF(x,800))
            event=QMouseEvent(kind,pos,Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(canvas,event)
        self.after(self.external_checked,300)
    def external_checked(self):
        self.doc.waitForDone()
        external=bytes(self.layer.projectionPixelData(760,760,100,100))
        assert external!=self.external_before
        from linework.animation import record
        try: record(self.doc,self.layer)
        except ValueError as exc: assert 'preserved' in str(exc)
        else: raise AssertionError('External pixels were not detected')
        assert bytes(self.layer.projectionPixelData(760,760,100,100))==external
        self.undo()
        assert len(record(self.doc,self.layer)['strokes'])==1
        self.result['external_raster_edit_is_preserved_and_blocks_linework_overwrite']='pass'
        self.result.update(result='pass',krita=self.k.version()); self.finish()

Krita.instance().addExtension(Probe(Krita.instance()))
