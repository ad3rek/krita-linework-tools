# SPDX-License-Identifier: GPL-3.0-or-later
"""Native static transforms, point input and .kra persistence with timers enabled."""
import copy
import faulthandler
import json
import os
import time
import traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import (QApplication,QTimer,QDialog,QEvent,QPointF,QMouseEvent,Qt,QTest)
from linework.animation import AnimationBusy

ROOT=Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result={};self.tries=0;self.after(self.start,1800)
        self.stack=(ROOT/'python-stack.log').open('w')
        faulthandler.dump_traceback_later(12,repeat=True,file=self.stack)

    def createActions(self,window):pass
    def after(self,fn,delay=350):QTimer.singleShot(delay,lambda:self.safe(fn))
    def safe(self,fn):
        try:
            (ROOT/'phase.json').write_text(json.dumps({'phase':fn.__name__,'completed':self.result}))
            fn()
        except AnimationBusy:self.after(fn,100)
        except Exception:
            self.result.update(result='fail',traceback=traceback.format_exc());self.finish()

    def start(self):
        self.k=Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className()=='KisAutoSaveRecoveryDialog':QDialog.reject(widget)
        for window in self.k.windows():window.activate();QApplication.setActiveWindow(window.qwindow())
        self.window=self.k.activeWindow()
        if not self.window or not self.k.activeDocument():
            self.tries+=1;assert self.tries<40;self.after(self.start);return
        self.window.qwindow().resize(1450,1020)
        self.doc=self.k.activeDocument();self.view=self.window.activeView()
        from linework.model import Point,Stroke
        from linework.native_brush import capture_brush,NativeBrushRenderer
        from linework.storage import write_layer
        from linework.tools import select_tool,current_controller
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.k.action('erase_action').setChecked(False)
        strokes=[Stroke([Point(160,180,.6),Point(320,320,.8),Point(550,200,.4)],width=24,
                        brush=copy.deepcopy(capture_brush(self.view))),
                 Stroke([Point(200,400),Point(510,430)],width=15,color='#3d7095')]
        renderer=NativeBrushRenderer(self.view)
        self.layer=self.doc.createNode('Static Linework','vectorlayer')
        assert self.doc.rootNode().addChildNode(self.layer,None)
        self.layer=write_layer(self.doc,self.layer,strokes,renderer);renderer.close()
        self.doc.setActiveNode(self.layer)
        self.initial=[stroke.data() for stroke in strokes]
        select_tool(3);self.controller=current_controller(self.window);self.controller.poll()
        self.controller.overlay.sync_transform()
        self.canvas=self.controller.native_widget
        self.image_to_widget=self.controller.overlay.image_to_widget
        from linework.native_brush import shape_frame
        from linework.transforms import coefficients
        self.result['before_transform']={'position':[self.layer.position().x(),self.layer.position().y()], 'shapes':[(shape.name(),coefficients(shape_frame(shape))) for shape in self.layer.shapes()]}
        self.initial_pixels=bytes(self.layer.projectionPixelData(0,0,900,900))
        self.transforms=['move','scale','rotate'];self.index=0
        self.after(self.activate)

    def activate(self):
        # Reenter Transform so each operation gets its own initialized native
        # preview, instead of clicking a not-yet-started second gesture.
        self.k.action('KritaShape/KisToolBrush').trigger()
        action=self.k.action('KisToolTransform');assert action and action.isEnabled()
        self.canvas.setFocus();action.trigger()
        self.started=time.monotonic()
        self.after(self.gesture,500)

    def pointer(self,kind,x,y):
        pos=self.image_to_widget.map(QPointF(x,y))
        event=QMouseEvent(kind,pos,
            Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.canvas,event)

    def gesture(self):
        from linework.qt import QObject,QMetaObject,Q_ARG
        widget=next(w for w in self.window.qwindow().findChildren(QObject)
                    if w.metaObject().className()=='KisToolTransformConfigWidget')
        def change(slot,kind,value):
            QMetaObject.invokeMethod(widget,slot,Qt.ConnectionType.DirectConnection,Q_ARG(kind,value))
        self.before=bytes(self.layer.projectionPixelData(0,0,900,900))
        mode=self.transforms[self.index]
        if mode=='move':
            box=widget.findChild(QObject,'translateXBox')
            change('slotSetTranslateX','int',int(box.property('value'))+40)
        elif mode=='scale':
            change('slotSetScaleX','int',120);change('slotSetScaleY','int',115)
        else:
            change('slotSetAZ','qreal',15.0)
        self.after(self.apply,500)

    def apply(self):
        # Enter applies through the same native input path as interactive use.
        QTest.keyClick(self.canvas,Qt.Key.Key_Return)
        self.after(self.applied,700)

    def applied(self):
        self.doc.waitForDone()
        mode=self.transforms[self.index]
        assert time.monotonic()-self.started<10,'GUI event loop stalled during '+mode
        self.result[mode+'_keeps_event_loop_responsive']='pass'
        self.window.qwindow().grab().save(str(ROOT/'docs/images'/('transform-'+mode+'.png')))
        assert bytes(self.layer.projectionPixelData(0,0,900,900))!=self.before,mode+' did not transform native pixels'
        self.result[mode+'_applies_native_transformed_pixels']='pass'
        from linework.storage import read_layer
        changed=read_layer(self.doc,self.layer,self.view)
        from linework.native_brush import shape_frame
        from linework.transforms import coefficients
        self.result['after_'+mode]={'position':[self.layer.position().x(),self.layer.position().y()], 'shapes':[(shape.name(),coefficients(shape_frame(shape))) for shape in self.layer.shapes()]}
        assert changed and [stroke.data() for stroke in changed] != self.initial
        self.result[mode+'_preserves_editable_geometry']='pass'
        if getattr(self,'edit_after',False):self.after(self.edit_point);return
        self.index+=1
        if self.index<len(self.transforms):self.after(self.activate);return
        self.window.qwindow().grab().save(str(ROOT/'docs/images/native-transform.png'))
        self.undo_count=0;self.after(self.undo)

    def undo(self):
        self.k.action('edit_undo').trigger();self.doc.waitForDone()
        self.undo_count+=1
        if bytes(self.layer.projectionPixelData(0,0,900,900))==self.initial_pixels:
            self.after(self.restored);return
        if self.undo_count<3:self.after(self.undo);return
        self.after(self.restored)

    def restored(self):
        from linework.storage import read_layer
        from linework.tools import select_tool,current_controller
        select_tool(3);self.controller=current_controller(self.window);self.controller.poll()
        self.doc.waitForDone()
        assert bytes(self.layer.projectionPixelData(0,0,900,900))==self.initial_pixels
        self.result['native_undo_restores_exact_original_pixels']='pass'
        from linework.model import load_strokes,segment_controls
        initial=load_strokes(self.initial);restored=read_layer(self.doc,self.layer)
        for old,new in zip(initial,restored):
            assert old.uid==new.uid and abs(old.width-new.width)<1e-6
            for a,b in zip(old.points,new.points):
                assert abs(a.x-b.x)<1e-6 and abs(a.y-b.y)<1e-6
            for i in range(len(old.points)-1):
                for a,b in zip(segment_controls(old,i),segment_controls(new,i)):
                    assert abs(a.x-b.x)<1e-6 and abs(a.y-b.y)<1e-6
        self.result['native_undo_restores_editable_linework']='pass'
        self.edit_after=True;self.transforms=['scale'];self.index=0;self.after(self.activate)

    def edit_point(self):
        from linework.tools import select_tool,current_controller
        from linework.storage import read_layer,write_layer
        from linework.native_brush import shape_frame
        from linework.transforms import coefficients
        select_tool(3);self.controller=current_controller(self.window);self.controller.poll()
        assert self.controller.overlay and not self.controller._error,self.controller.status.text()
        self.controller.selection_mode.setCurrentIndex(1)
        overlay=self.controller.overlay;overlay.selection.clear();overlay.sync_transform()
        self.canvas=self.controller.native_widget;self.image_to_widget=overlay.image_to_widget
        before=copy.deepcopy([s.data() for s in overlay.strokes]);point=overlay.strokes[0].points[0]
        start=(point.x,point.y);end=(point.x+15,point.y+12)
        self.pointer(QEvent.Type.MouseButtonPress,*start)
        assert overlay.drag=='point'
        self.pointer(QEvent.Type.MouseMove,*end)
        self.pointer(QEvent.Type.MouseButtonRelease,*end)
        assert not self.controller._error,self.controller.status.text()
        actual=[s.data() for s in read_layer(self.doc,self.layer)]
        assert abs(actual[0]['points'][0][0]-end[0])<1e-6
        assert abs(actual[0]['points'][0][1]-end[1])<1e-6
        assert actual[1]==before[1]
        shape=next(s for s in self.layer.shapes() if s.name()=='lw_'+actual[0]['id'])
        self.result['edited_shape_frame']=coefficients(shape_frame(shape))
        assert all(abs(a-b)<1e-8 for a,b in zip(coefficients(shape_frame(shape)),[1,0,0,1,0,0])), self.result['edited_shape_frame']
        self.result['point_drag_after_resize_uses_world_coordinates']='pass'
        self.saved_data=actual;path=ROOT/'examples/static-transformed.kra'
        assert self.doc.saveAs(str(path))
        loaded=self.k.openDocument(str(path));assert loaded
        node=loaded.nodeByUniqueID(self.layer.uniqueId())
        assert [s.data() for s in read_layer(loaded,node)]==actual
        loaded.setModified(False);loaded.close()
        self.result['transformed_and_edited_kra_reopens_editable']='pass'
        self.result.update(result='pass',krita=self.k.version());self.finish()

    def finish(self):
        faulthandler.cancel_dump_traceback_later();self.stack.close()
        (ROOT/'docs/validation/static-transform.json').write_text(json.dumps(self.result,indent=2))
        for doc in self.k.documents():doc.setModified(False)
        self.layer=self.doc=self.view=self.controller=self.canvas=None
        if hasattr(self,'window'):self.window.qwindow().close()
        QTimer.singleShot(300,QApplication.instance().quit)


Krita.instance().addExtension(Probe(Krita.instance()))
