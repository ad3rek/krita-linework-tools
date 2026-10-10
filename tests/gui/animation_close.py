# SPDX-License-Identifier: GPL-3.0-or-later
"""Close multiple animated views, including a cancelled close, without stale tools."""
import json,os,traceback
from pathlib import Path
from krita import Krita,Extension
from linework.qt import QApplication,QTimer,QCloseEvent,QEventLoop,QKeyEvent,QEvent,Qt,QDialog
ROOT=Path(os.environ['LINEWORK_TEST_ROOT'])
class Probe(Extension):
    def setup(self):self.result={};self.tries=0;self.after(self.start,2000)
    def createActions(self,window):pass
    def after(self,fn,delay=300):
        def run():
            try:
                (ROOT/'phase.json').write_text(json.dumps({'phase':fn.__name__,'completed':self.result}))
                fn()
            except Exception:self.fail()
        QTimer.singleShot(delay,run)
    def start(self):
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self.k=Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        windows = [window for window in self.k.windows() if window.activeView() and window.activeView().document()]
        if not windows:
            self.tries+=1;assert self.tries<300;self.after(self.start);return
        self.window=windows[0]
        self.window.activate();QApplication.setActiveWindow(self.window.qwindow())
        self.doc=self.window.activeView().document()
        self.after(self.ready)
    def ready(self):
        from linework.tools import select_tool,current_controller
        from linework.model import Point,Stroke
        from linework.storage import write_layer
        select_tool(3);self.c=current_controller(self.window)
        if self.c is None:
            self.tries+=1;assert self.tries<300;self.after(self.ready);return
        self.layer=self.c.create_native_layer(self.doc)
        write_layer(self.doc,self.layer,[Stroke([Point(100,100),Point(250,200)],width=12)])
        self.doc.waitForDone();self.c.poll()
        self.after(self.converted)
    def converted(self):
        self.c.poll();assert self.c.layer.type()=='paintlayer',self.c.status.text()
        self.result['animated_view_is_editable']='pass'
        # Simulate a Close event which a Save/Close dialog subsequently ignores.
        self.c.canvas_event(self.window.qwindow(),QCloseEvent())
        self.after(self.cancelled,500)
    def cancelled(self):
        assert self.c._window_closing and not self.c.active
        QApplication.sendEvent(self.window.qwindow(),QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Escape,Qt.KeyboardModifier.NoModifier))
        self.c.poll();assert self.c.active and self.c.overlay and self.c.layer.type()=='paintlayer'
        self.result['cancelled_close_restores_editable_tool']='pass'
        self.path=ROOT/'examples/animated.kra'
        assert self.doc.saveAs(str(self.path));self.doc.waitForDone()
        self.second=self.k.openDocument(str(self.path));assert self.second
        self.window.addView(self.second)
        self.after(self.bound,500)
    def bound(self):
        from linework.tools import select_tool,current_controller
        from linework.storage import metadata,layer_id
        self.second.waitForDone();data=metadata(self.second)['layers']
        self.layer=next(n for n in self.second.rootNode().findChildNodes('',True,False,'paintlayer') if data.get(layer_id(n),{}).get('kind')=='animated')
        self.second.setActiveNode(self.layer);select_tool(3);self.c=current_controller(self.window)
        self.after(self.close,500)
    def close(self):
        self.c.poll();assert self.c.overlay and self.c.layer.type()=='paintlayer',self.c.status.text()
        self.result['reopened_second_view_is_editable']='pass'
        for d in self.k.documents():d.setModified(False)
        self.result.update(result='pass',krita=self.k.version())
        (ROOT/'docs/validation/animation-close.json').write_text(json.dumps(self.result,indent=2))
        self.window.qwindow().close()
        QTimer.singleShot(300,QApplication.instance().quit)
    def fail(self):
        self.result.update(result='fail',traceback=traceback.format_exc())
        (ROOT/'docs/validation/animation-close.json').write_text(json.dumps(self.result,indent=2))
        for d in Krita.instance().documents():d.setModified(False)
        QTimer.singleShot(100,QApplication.instance().quit)
Krita.instance().addExtension(Probe(Krita.instance()))
