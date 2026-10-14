# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy whole Linework layers through Krita's ordinary and layer actions."""
import copy
import json
import logging
import os
import time
import traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QApplication, QTimer, QDialog, QTest, Qt
from linework.animation import AnimationBusy

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        logger=logging.getLogger('linework.clipboard')
        logger.addHandler(logging.StreamHandler());logger.setLevel(logging.DEBUG)
        self.result = {'cases': {}, 'failures': []}
        self.tries = 0
        self.after(self.start, 1800)

    def createActions(self, window): pass

    def after(self, fn, delay=350):
        QTimer.singleShot(delay, lambda: self.safe(fn))

    def safe(self, fn):
        try:
            (ROOT/'phase.json').write_text(json.dumps({'phase': fn.__name__, 'completed': self.result}))
            fn()
        except AnimationBusy:
            self.after(fn, 100)
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc())
            self.finish()

    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows():
            window.activate(); QApplication.setActiveWindow(window.qwindow())
        self.window = self.k.activeWindow()
        if not self.window or not self.k.activeDocument():
            self.tries += 1
            assert self.tries < 40
            self.after(self.start); return
        self.window.qwindow().resize(1450, 1020)
        self.source = self.k.activeDocument()
        self.source_view = self.window.activeView()
        from linework.model import Point, Stroke
        from linework.native_brush import capture_brush, NativeBrushRenderer
        from linework.storage import write_layer
        self.source_view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.k.action('erase_action').setChecked(False)
        brush = capture_brush(self.source_view)
        strokes = [Stroke([Point(120,180,.6), Point(300,260,.8), Point(500,180,.4)],
                          width=18, brush=copy.deepcopy(brush)),
                   Stroke([Point(120,430), Point(500,430)], width=12, color='#3d7095')]
        renderer = NativeBrushRenderer(self.source_view)
        self.layer = write_layer(self.source, None, strokes, renderer)
        renderer.close()
        self.initial = [s.data() for s in strokes]
        from linework.animation import call
        call('frame_action', self.layer, 2, 0, 8)
        self.source.setCurrentTime(8); self.source.waitForDone()
        strokes[0].width = 27
        renderer = NativeBrushRenderer(self.source_view)
        write_layer(self.source, self.layer, strokes, renderer); renderer.close()
        self.second = [s.data() for s in strokes]
        self.source.setCurrentTime(0); self.source.waitForDone()
        self.source_pixels = bytes(self.layer.pixelData(0,0,900,900))
        self.modes = [('standard', 'edit_copy', 'edit_paste'),
                      ('layers', 'copy_layer_clipboard', 'paste_layer_from_clipboard')]
        self.index = 0
        self.after(self.copy_layer)

    def copy_layer(self):
        from linework.tools import select_tool
        self.window.showView(self.source_view)
        self.source.setActiveNode(self.layer)
        select_tool(0)
        self.source.waitForDone()
        self.mode, copy_id, self.paste_id = self.modes[self.index]
        action = self.k.action(copy_id)
        assert action, copy_id
        assert action.isEnabled(), copy_id
        if self.mode == 'standard':
            QTest.keyClick(self.window.qwindow(),Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
        else:
            action.trigger()
        self.after(self.create_target)

    def create_target(self):
        self.result['cases'][self.mode] = {'clipboard_formats': list(QApplication.clipboard().mimeData().formats())}
        self.target = self.k.createDocument(1200,1100,'Linework transfer '+self.mode,
                                           'RGBA','U8','sRGB-elle-V2-srgbtrc.icc',72)
        self.window.addView(self.target)
        self.after(self.paste_layer)

    def paste_layer(self):
        action = self.k.action(self.paste_id)
        assert action and action.isEnabled(), self.paste_id
        if self.mode == 'standard':
            QTest.keyClick(self.window.qwindow(),Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
        else:
            action.trigger()
        self.paste_deadline=time.monotonic()+12
        self.after(self.pasted, 700)

    def pasted(self):
        from linework.storage import read_layer, layer_id, metadata
        from linework.animation import call
        self.target.waitForDone()
        self.pasted_layer = self.target.activeNode()
        assert self.pasted_layer
        case = self.result['cases'][self.mode]
        case.update(source_layer_id=layer_id(self.layer), pasted_layer_id=layer_id(self.pasted_layer),
                    layer_type=self.pasted_layer.type(), layer_name=self.pasted_layer.name(),
                    selected_nodes=[(node.name(),layer_id(node)) for node in self.window.activeView().selectedNodes()],
                    saved_metadata=metadata(self.target))
        try:
            strokes = read_layer(self.target,self.pasted_layer)
        except ValueError as exc:
            self.result['failures'].append(self.mode+': '+str(exc))
            self.after(self.next_case); return
        if strokes is None:
            if (QApplication.clipboard().mimeData().hasFormat('application/x-krita-linework-layers-v1')
                    and time.monotonic()<self.paste_deadline):
                self.after(self.pasted,100);return
            self.result['failures'].append(self.mode+': pasted layer has no editable Linework geometry')
            self.after(self.next_case); return
        assert [s.data() for s in strokes] == self.initial
        self.result[self.mode+'_current_frame_keeps_exact_geometry'] = 'pass'
        assert bytes(self.pasted_layer.pixelData(0,0,900,900)) == self.source_pixels
        self.result[self.mode+'_keeps_exact_pixels'] = 'pass'
        info = call('info',self.pasted_layer,1)
        assert [f['time'] for f in info['frames']] == [0,8], info
        from linework.frame_payload import expand_record
        frame8=next(frame for frame in info['frames'] if frame['time']==8)
        assert expand_record(frame8['payload'])['strokes'] == self.second
        self.result[self.mode+'_keeps_other_animation_frames'] = 'pass'
        self.pasted_id=self.pasted_layer.uniqueId()
        self.after(self.undo_paste)

    def undo_paste(self):
        action=self.k.action('edit_undo')
        if not action.isEnabled():
            assert time.monotonic()<self.paste_deadline,'Native Undo did not become enabled'
            self.after(self.undo_paste,100);return
        self.result['cases'][self.mode]['paste_undo_action']=self.k.action('edit_undo').text()
        self.k.action('edit_undo').trigger()
        self.after(self.paste_undone,500)

    def paste_undone(self):
        self.target.waitForDone()
        # libkis can still find a detached node retained by the Undo command.
        # The visible document tree is authoritative for paste removal.
        live_ids=[node.uniqueId() for node in self.target.rootNode().findChildNodes('',True,False)]
        self.result['cases'][self.mode]['nodes_after_paste_undo']=[str(uid.toString()) for uid in live_ids]
        assert self.pasted_id not in live_ids
        self.result[self.mode+'_paste_is_one_native_undo_step']='pass'
        self.k.action('edit_redo').trigger();self.target.waitForDone()
        self.after(self.paste_redone)

    def paste_redone(self):
        from linework.storage import read_layer
        self.pasted_layer=self.target.nodeByUniqueID(self.pasted_id)
        assert self.pasted_layer and [s.data() for s in read_layer(self.target,self.pasted_layer)]==self.initial
        self.result[self.mode+'_paste_redo_keeps_editable_geometry']='pass'
        self.target.setCurrentTime(8);self.target.waitForDone()
        assert [s.data() for s in read_layer(self.target,self.pasted_layer)]==self.second
        self.target.setCurrentTime(0);self.target.waitForDone()
        from linework.tools import select_tool,current_controller
        select_tool(3); self.controller = current_controller(self.window)
        self.controller.poll()
        assert self.controller.overlay and self.controller.overlay.strokes
        self.controller.overlay.strokes[0].points[0].x += 10
        self.controller.overlay.commit()
        self.after(self.edited)

    def edited(self):
        from linework.storage import read_layer
        self.target.waitForDone()
        strokes=read_layer(self.target,self.pasted_layer)
        assert strokes[0].points[0].x == self.initial[0]['points'][0][0]+10
        self.result[self.mode+'_pasted_geometry_can_be_edited'] = 'pass'
        assert bytes(self.layer.pixelData(0,0,900,900)) == self.source_pixels
        self.result[self.mode+'_editing_target_preserves_source'] = 'pass'
        self.k.action('edit_undo').trigger(); self.target.waitForDone()
        assert [s.data() for s in read_layer(self.target,self.pasted_layer)] == self.initial
        self.result[self.mode+'_native_undo_restores_geometry'] = 'pass'
        self.k.action('edit_redo').trigger(); self.target.waitForDone()
        self.edited_geometry=[s.data() for s in read_layer(self.target,self.pasted_layer)]
        assert self.edited_geometry[0]['points'][0][0] == self.initial[0]['points'][0][0]+10
        self.result[self.mode+'_native_redo_restores_geometry'] = 'pass'
        self.path=ROOT/'examples'/('clipboard-'+self.mode+'.kra')
        self.target.setBatchmode(True)
        assert self.target.saveAs(str(self.path))
        self.target.setBatchmode(False)
        self.target.setModified(False)
        self.reopened=self.k.openDocument(str(self.path)); assert self.reopened
        self.window.addView(self.reopened)
        self.after(self.reloaded,500)

    def reloaded(self):
        from linework.storage import metadata,read_layer,layer_id
        self.reopened.waitForDone()
        records=metadata(self.reopened)['layers']
        self.reopened_layer=next(layer for layer in self.reopened.rootNode().findChildNodes('',True,False,'paintlayer')
                                 if records.get(layer_id(layer),{}).get('kind')=='animated')
        assert [s.data() for s in read_layer(self.reopened,self.reopened_layer)] == self.edited_geometry
        self.reopened.setCurrentTime(8); self.reopened.waitForDone()
        assert [s.data() for s in read_layer(self.reopened,self.reopened_layer)] == self.second
        self.result[self.mode+'_save_reopen_preserves_editable_frames'] = 'pass'
        self.reopened.setCurrentTime(0); self.reopened.waitForDone()
        self.window.qwindow().grab().save(str(ROOT/'docs/images'/('clipboard-'+self.mode+'.png')))
        self.after(self.next_case)

    def next_case(self):
        self.index += 1
        if self.index < len(self.modes): self.after(self.copy_layer); return
        if not self.result['failures']:
            self.after(self.ordinary_copy);return
        self.result.update(result='pass' if not self.result['failures'] else 'fail',krita=self.k.version())
        self.finish()

    def ordinary_copy(self):
        self.window.showView(self.source_view)
        self.ordinary=self.source.createNode('Ordinary raster clipboard','paintlayer')
        self.source.rootNode().addChildNode(self.ordinary,None)
        self.ordinary_pixels=bytes([90,180,70,255])*16
        self.ordinary.setPixelData(self.ordinary_pixels,10,10,4,4)
        self.source.setActiveNode(self.ordinary);self.source.refreshProjection();self.source.waitForDone()
        self.k.action('copy_layer_clipboard').trigger()
        self.after(self.ordinary_paste)

    def ordinary_paste(self):
        assert not QApplication.clipboard().mimeData().hasFormat('application/x-krita-linework-layers-v1')
        self.result['ordinary_raster_copy_does_not_reuse_linework_clipboard_data']='pass'
        self.ordinary_target=self.k.createDocument(1200,1100,'Ordinary clipboard target','RGBA','U8','sRGB-elle-V2-srgbtrc.icc',72)
        self.window.addView(self.ordinary_target)
        self.after(self.ordinary_insert)

    def ordinary_insert(self):
        self.k.action('paste_layer_from_clipboard').trigger()
        self.after(self.ordinary_checked,700)

    def ordinary_checked(self):
        from linework.storage import metadata,layer_id,read_layer
        self.ordinary_target.waitForDone()
        self.ordinary_pasted=self.ordinary_target.activeNode()
        assert self.ordinary_pasted and bytes(self.ordinary_pasted.pixelData(10,10,4,4))==self.ordinary_pixels
        assert layer_id(self.ordinary_pasted) not in metadata(self.ordinary_target)['layers']
        assert read_layer(self.ordinary_target,self.ordinary_pasted) is None
        self.result['ordinary_raster_paste_keeps_pixels_and_remains_ordinary']='pass'
        self.result.update(result='pass',krita=self.k.version());self.finish()

    def finish(self):
        (ROOT/'docs/validation/clipboard.json').write_text(json.dumps(self.result,indent=2))
        for doc in self.k.documents(): doc.setModified(False)
        for name in ('layer','pasted_layer','target','source','source_view','reopened','reopened_layer','controller',
                     'ordinary','ordinary_target','ordinary_pasted'):
            setattr(self,name,None)
        if hasattr(self,'window'):self.window.qwindow().close()
        QTimer.singleShot(300,QApplication.instance().quit)


Krita.instance().addExtension(Probe(Krita.instance()))
