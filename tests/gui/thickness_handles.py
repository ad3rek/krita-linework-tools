# SPDX-License-Identifier: GPL-3.0-or-later
"""Drag the visible diameter handles through Krita's canvas event path."""
import copy
import json
import math
import os
import traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QApplication, QTimer, QDialog, QDockWidget, QEvent, QMouseEvent, QPointF, Qt

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()

class Probe(Extension):
    def setup(self):
        self.result = {}; self.after(self.start, 1800)
    def createActions(self, window): pass
    def after(self, fn, ms=200): QTimer.singleShot(ms, lambda: self.safe(fn))
    def safe(self, fn):
        try:
            if hasattr(self, 'c') and self.c.input_busy():
                self.after(fn); return
            (ROOT/'phase.json').write_text(json.dumps({'phase':fn.__name__, 'completed':self.result}))
            fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc()); self.finish()
    def finish(self):
        (ROOT/'docs/validation/thickness-handles.json').write_text(json.dumps(self.result, indent=2))
        for d in Krita.instance().documents(): d.setModified(False)
        if hasattr(self, 'window'): self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)
    def start(self):
        self.k = Krita.instance()
        for w in QApplication.topLevelWidgets():
            if w.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(w)
        if not self.k.activeDocument(): self.after(self.start); return
        self.window = self.k.activeWindow(); self.window.activate()
        QApplication.setActiveWindow(self.window.qwindow()); self.window.qwindow().resize(1450,1020)
        dock=self.window.qwindow().findChild(QDockWidget,'sharedtooldocker')
        dock.show();dock.raise_()
        self.view = self.window.activeView(); self.doc = self.view.document()
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-1'])
        self.view.setBrushSize(40)
        from linework.tools import select_tool, current_controller
        from linework.model import Point, Stroke
        from linework.native_brush import capture_brush, NativeBrushRenderer
        from linework.storage import write_layer
        select_tool(4); self.c = current_controller(self.window)
        self.layer = self.c.create_native_layer(self.doc)
        self.stroke = Stroke([Point(450,450,1),Point(470,470,1)], width=40, brush=capture_brush(self.view))
        renderer = NativeBrushRenderer(self.view)
        write_layer(self.doc, self.layer, [self.stroke], renderer); renderer.close()
        self.c.clear_binding(); self.c.poll()
        self.c.selection_mode.setCurrentIndex(1)
        self.c.overlay.selection.set_points([(self.stroke.uid,0)])
        self.c.overlay.selectedChanged.emit()
        self.cases = [(1.0,1,False),(10.67,-1,False),(10.67,1,True)]
        self.after(self.zoom)
    def zoom(self):
        if not self.cases:
            self.after(self.reject_unsupported); return
        self.zoom_level, self.side, self.locked = self.cases.pop(0)
        self.view.canvas().setZoomLevel(self.zoom_level)
        self.after(self.drag)
    def event(self, kind, pos):
        self.c._tablet_until = 0
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        QApplication.sendEvent(self.c.native_widget,QMouseEvent(kind,pos,button,buttons,Qt.KeyboardModifier.NoModifier))
        assert self.c.overlay and not self.c._error, self.c.status.text()
    def drag(self):
        o = self.c.overlay; o.sync_transform()
        assert math.isclose(o.zoom,self.zoom_level,rel_tol=.001),(o.zoom,self.zoom_level)
        s = o.strokes[0]; self.before = copy.deepcopy(s.data())
        self.pixels = bytes(self.layer.projectionPixelData(0,0,self.doc.width(),self.doc.height()))
        o.selection.set_points([(s.uid,0)])
        o.locked_point = (s.uid,0) if self.locked else None
        o.selectedChanged.emit()
        (nx,ny), radius = o.thickness_guide(s,0)
        p = s.points[0]
        start = o.image_to_widget.map(QPointF(p.x+self.side*nx*radius,p.y+self.side*ny*radius))
        # The endpoint is well outside the anchor's screen-space click radius.
        assert radius*o.zoom > o.pick_radius
        finish = o.image_to_widget.map(QPointF(p.x+self.side*nx*(radius+2),p.y+self.side*ny*(radius+2)))
        self.event(QEvent.Type.MouseButtonPress,start)
        assert o.drag == 'pressure' and o.selection.primary == (s.uid,0)
        self.event(QEvent.Type.MouseMove,finish)
        assert o.selection.primary == (s.uid,0) and self.c.thickness.isEnabled()
        assert math.isclose(s.width*s.points[0].thickness,44,abs_tol=1e-6)
        assert s.points[1].thickness is None or s.width*s.points[1].thickness == 40
        self.event(QEvent.Type.MouseButtonRelease,finish)
        self.after(self.check)
    def check(self):
        from linework.storage import read_layer
        o = self.c.overlay; s = o.strokes[0]
        assert o.selection.primary == (s.uid,0) and self.c.thickness.isEnabled()
        assert [[p.x,p.y] for p in s.points] == [p[:2] for p in self.before['points']]
        assert read_layer(self.doc,self.layer)[0].data() == s.data()
        assert bytes(self.layer.projectionPixelData(0,0,self.doc.width(),self.doc.height())) != self.pixels
        if self.zoom_level > 10:
            self.window.qwindow().grab().save(str(ROOT/'docs/images/thickness-handle-high-zoom.png'))
        self.result[f'zoom_{self.zoom_level}_side_{self.side}_locked_{self.locked}'] = 'pass'
        o.undo(); assert o.strokes[0].data() == self.before
        assert bytes(self.layer.projectionPixelData(0,0,self.doc.width(),self.doc.height())) == self.pixels
        self.after(self.zoom)

    def reject_unsupported(self):
        from linework.model import Point, Stroke
        from linework.native_brush import capture_brush, NativeBrushRenderer
        from linework.storage import write_layer
        self.view.canvas().setZoomLevel(1)
        self.view.setCurrentBrushPreset(self.k.resources('preset')['v) Sketching-1 Chrome Thin'])
        s=Stroke([Point(500,500),Point(510,520)],width=20,brush=capture_brush(self.view))
        renderer=NativeBrushRenderer(self.view)
        write_layer(self.doc,self.layer,[self.c.overlay.strokes[0],s],renderer);renderer.close()
        self.c.clear_binding();self.c.poll()
        self.unsupported=s.uid
        self.after(self.rejected_drag)

    def rejected_drag(self):
        o=self.c.overlay;o.sync_transform()
        o.selection.set_points([(self.unsupported,0)]);o.selectedChanged.emit()
        before=[s.data() for s in o.strokes]
        pixels=bytes(self.layer.projectionPixelData(0,0,self.doc.width(),self.doc.height()))
        depth=len(o.history.undo_stack)
        start=o.image_to_widget.map(QPointF(500,500));end=o.image_to_widget.map(QPointF(500,496))
        for kind,pos in ((QEvent.Type.MouseButtonPress,start),(QEvent.Type.MouseMove,end),(QEvent.Type.MouseButtonRelease,end)):
            self.event(kind,pos)
        assert self.c.overlay is o and o.selection.primary==(self.unsupported,0)
        assert self.c.thickness.isEnabled() and o.drag is None
        assert [s.data() for s in o.strokes]==before and len(o.history.undo_stack)==depth
        assert bytes(self.layer.projectionPixelData(0,0,self.doc.width(),self.doc.height()))==pixels
        self.result['rejected_engine_preserves_selection_geometry_appearance_and_history']='pass'
        self.result.update(result='pass',krita=self.k.version());self.finish()

Krita.instance().addExtension(Probe(Krita.instance()))
