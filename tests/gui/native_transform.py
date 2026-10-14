# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the native Transform tool with Linework timers enabled."""
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
        self.layer=write_layer(self.doc,None,strokes,renderer);renderer.close()
        self.initial=[stroke.data() for stroke in strokes]
        select_tool(3);self.controller=current_controller(self.window);self.controller.poll()
        self.controller.overlay.sync_transform()
        self.canvas=self.controller.native_widget
        self.image_to_widget=self.controller.overlay.image_to_widget
        self.initial_pixels=bytes(self.layer.pixelData(0,0,900,900))
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
        # waitForDone() requests native stroke-end and would finish the live
        # Transform preview before our gesture. Wait through Qt timers instead.
        self.image_to_widget=(self.view.flakeToImageTransform().inverted()[0]*
                              self.view.flakeToCanvasTransform())
        rect=self.layer.bounds();mode=self.transforms[self.index]
        if mode=='move':
            start=(rect.center().x(),rect.center().y());end=(start[0]+40,start[1]+30)
        elif mode=='scale':
            start=(rect.right(),rect.bottom());end=(start[0]+45,start[1]+25)
        else:
            start=(rect.right()+30,rect.top()-30);end=(rect.right()+10,rect.top()+40)
        self.before=bytes(self.layer.pixelData(0,0,900,900))
        self.pointer(QEvent.Type.MouseButtonPress,*start)
        for step in range(1,6):
            t=step/5
            self.pointer(QEvent.Type.MouseMove,start[0]+t*(end[0]-start[0]),start[1]+t*(end[1]-start[1]))
        self.pointer(QEvent.Type.MouseButtonRelease,*end)
        self.after(self.apply,300)

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
        assert bytes(self.layer.pixelData(0,0,900,900))!=self.before,mode+' did not transform native pixels'
        self.result[mode+'_applies_native_transformed_pixels']='pass'
        self.index+=1
        if self.index<len(self.transforms):self.after(self.activate);return
        self.window.qwindow().grab().save(str(ROOT/'docs/images/native-transform.png'))
        self.undo_count=0;self.after(self.undo)

    def undo(self):
        self.k.action('edit_undo').trigger();self.doc.waitForDone()
        self.undo_count+=1
        if bytes(self.layer.pixelData(0,0,900,900))==self.initial_pixels:
            self.after(self.restored);return
        if self.undo_count<3:self.after(self.undo);return
        self.after(self.restored)

    def restored(self):
        from linework.storage import read_layer
        from linework.tools import select_tool,current_controller
        select_tool(3);self.controller=current_controller(self.window);self.controller.poll()
        self.doc.waitForDone()
        assert bytes(self.layer.pixelData(0,0,900,900))==self.initial_pixels
        self.result['native_undo_restores_exact_original_pixels']='pass'
        assert [stroke.data() for stroke in read_layer(self.doc,self.layer)]==self.initial
        self.result['native_undo_restores_editable_linework']='pass'
        self.result.update(result='pass',krita=self.k.version());self.finish()

    def finish(self):
        faulthandler.cancel_dump_traceback_later();self.stack.close()
        (ROOT/'docs/validation/native-transform.json').write_text(json.dumps(self.result,indent=2))
        for doc in self.k.documents():doc.setModified(False)
        self.layer=self.doc=self.view=self.controller=self.canvas=None
        if hasattr(self,'window'):self.window.qwindow().close()
        QTimer.singleShot(300,QApplication.instance().quit)


Krita.instance().addExtension(Probe(Krita.instance()))
