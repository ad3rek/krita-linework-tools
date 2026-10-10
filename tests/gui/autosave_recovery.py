# SPDX-License-Identifier: GPL-3.0-or-later
"""Reopen real native autosaves and edit vector and animated Linework layers."""
import copy
import json
import math
import os
import sys
import time
import traceback
import zipfile
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QApplication, QDialog, QTimer

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()
ANNOTATION = 'org.felipe.linework.v1'


class Probe(Extension):
    def setup(self):
        self.result = {}; self.tries = 0; self.event_failure = None
        sys.excepthook = self.event_error
        self.after(self.start, 1800)

    def createActions(self, window): pass

    def event_error(self, kind, value, tb):
        self.event_failure = ''.join(traceback.format_exception(kind,value,tb))

    def after(self, fn, delay=300):
        QTimer.singleShot(delay, lambda: self.safe(fn))

    def safe(self, fn):
        try:
            if self.event_failure: raise AssertionError(self.event_failure)
            if hasattr(self,'c') and (self.c.input_busy() or self.c._pending_input or self.c._brush_change is not None):
                self.after(fn, 100); return
            (ROOT/'phase.json').write_text(json.dumps({'phase':fn.__name__, 'completed':self.result}))
            fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc()); self.finish()

    def finish(self):
        self.result['krita'] = self.k.version()
        self.result['scope'] = 'Native timer-triggered background autosave, KRA reload and editing; no actual crash or startup recovery dialog.'
        (ROOT/'docs/validation/autosave-recovery.json').write_text(json.dumps(self.result, indent=2))
        for doc in self.k.documents(): doc.setModified(False)
        self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)

    def tool(self, mode):
        from linework.tools import select_tool, current_controller
        select_tool(mode); self.c = current_controller(self.window)
        assert self.c
        self.c.poll()
        assert self.c.overlay and not self.c._error, self.c.status.text()

    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        for window in self.k.windows():
            window.activate(); QApplication.setActiveWindow(window.qwindow())
        if not self.k.activeDocument():
            self.tries += 1; assert self.tries < 40
            self.after(self.start); return
        self.window = self.k.activeWindow(); self.window.qwindow().resize(1450, 1020)
        self.doc = self.window.activeView().document()
        assert self.doc.saveAs(str(ROOT/'examples/vector-source.kra'))
        self.view = self.window.activeView()
        self.view.setCurrentBrushPreset(self.k.resources('preset')['b) Basic-5 Size Opacity'])
        self.k.action('erase_action').setChecked(False)
        from linework.model import Point, Stroke
        from linework.native_brush import NativeBrushRenderer, capture_brush
        from linework.storage import write_layer
        self.tool(3); self.layer = self.c.create_native_layer(self.doc, 'vectorlayer')
        renderer = NativeBrushRenderer(self.view)
        points = [Point(120,180,.6),Point(300,260,.8),Point(500,180,.4)]
        strokes = [Stroke(points, width=18, brush=copy.deepcopy(capture_brush(self.view))),
                   Stroke([Point(120,430),Point(500,430)],width=12,color='#3d7095')]
        write_layer(self.doc,self.layer,strokes,renderer); renderer.close(); self.c.poll()
        self.kind = 'vector'; self.after(self.vector_ready)

    def vector_ready(self):
        self.c.poll()
        assert self.c.layer and self.c.layer.uniqueId() == self.layer.uniqueId()
        self.wait_autosave(self.vector_loaded)

    def wait_autosave(self, next_step):
        from linework.storage import metadata, layer_id
        self.next_step = next_step; self.layer_uid = self.layer.uniqueId()
        self.expected = [s.data() for s in self.c.overlay.strokes]
        self.record = metadata(self.doc)['layers'][layer_id(self.layer)]
        self.source_doc = self.doc
        filename = Path(self.doc.fileName()).name
        self.autosaves = [ROOT/'examples'/('.'+filename+'-autosave.kra'),
                          ROOT/'examples'/(filename+'-autosave.kra')]
        self.deadline = time.monotonic()+90
        self.after(self.autosaved, 1500)

    def autosaved(self):
        from linework.storage import layer_id
        payload = None
        for path in self.autosaves:
            try:
                with zipfile.ZipFile(path) as archive:
                    if archive.testzip() is not None: continue
                    entries = [n for n in archive.namelist() if n.endswith('/annotations/'+ANNOTATION)]
                    if len(entries) != 1: continue
                    payload = json.loads(archive.read(entries[0]))
                saved = payload['layers'].get(layer_id(self.layer))
                if self.kind == 'vector' and saved.get('strokes') != self.expected: continue
                if self.kind == 'animated' and saved.get('frames',{}).get('0',{}).get('strokes') != self.expected: continue
                self.autosave_path = path
                break
            except (OSError,zipfile.BadZipFile,KeyError,ValueError,AttributeError):
                payload = None
        else:
            assert time.monotonic() < self.deadline, 'Native autosave did not contain the expected Linework data'
            self.after(self.autosaved, 500); return
        self.result[self.kind+'_native_autosave_retains_editable_annotation'] = 'pass'
        # Preserve a copy because Krita removes autosaves when their source closes.
        (ROOT/'examples'/(self.kind+'-native-autosave.kra')).write_bytes(self.autosave_path.read_bytes())
        self.source_doc.setModified(False)
        self.doc = self.k.openDocument(str(self.autosave_path)); assert self.doc
        self.window.addView(self.doc)
        self.view = self.window.activeView(); self.layer = self.doc.nodeByUniqueID(self.layer_uid)
        assert self.layer
        self.doc.setActiveNode(self.layer)
        self.after(self.next_step, 500)

    def vector_loaded(self):
        from linework.storage import read_layer
        self.tool(3)
        assert [s.data() for s in read_layer(self.doc,self.layer,self.view)] == self.expected
        assert [s.data() for s in self.c.overlay.strokes] == self.expected
        self.result['vector_autosave_reopens_with_same_layer_and_strokes'] = 'pass'
        self.c.overlay.select_strokes([self.expected[0]['id']])
        # Test point and diameter edits independently on the recovered vector.
        self.c.overlay.strokes[0].points[0].x += 10
        self.c.overlay.commit()
        self.after(self.vector_point_edited)

    def vector_point_edited(self):
        from linework.storage import read_layer
        assert read_layer(self.doc,self.layer)[0].points[0].x == self.expected[0]['points'][0][0]+10
        self.result['vector_autosave_allows_point_edit'] = 'pass'
        self.c.overlay.undo(); self.tool(4)
        self.c.overlay.select_strokes([self.expected[0]['id']])
        self.c.thickness.setValue(9)
        self.after(self.vector_thickness_edited)

    def vector_thickness_edited(self):
        from linework.storage import read_layer
        from linework.native_brush import point_thickness
        strokes = read_layer(self.doc,self.layer)
        diameters = [point_thickness(strokes[0],i) for i in range(len(strokes[0].points))]
        assert all(math.isclose(d,9) for d in diameters), (diameters, self.c.status.text())
        self.result['vector_autosave_allows_thickness_edit'] = 'pass'
        self.k.action('edit_undo').trigger(); self.doc.waitForDone(); self.c.poll()
        assert [s.data() for s in read_layer(self.doc,self.layer)] == self.expected
        self.result['vector_autosave_native_undo_preserves_editability'] = 'pass'
        assert self.doc.saveAs(str(ROOT/'examples/animated-source.kra'))
        self.c.animate_layer(); self.after(self.animated_ready,500)

    def animated_ready(self):
        self.c.poll(); self.layer = self.c.layer
        assert self.layer and self.layer.type() == 'paintlayer', self.c.status.text()
        self.kind = 'animated'
        self.wait_autosave(self.animated_loaded)

    def animated_loaded(self):
        from linework.storage import read_layer
        self.doc.setCurrentTime(0); self.doc.waitForDone(); self.tool(4)
        assert [s.data() for s in read_layer(self.doc,self.layer)] == self.expected
        assert [s.data() for s in self.c.overlay.strokes] == self.expected
        self.result['animated_autosave_reopens_with_editable_frame'] = 'pass'
        self.c.overlay.select_strokes([self.expected[0]['id']]); self.c.thickness.setValue(11)
        self.after(self.animated_edited)

    def animated_edited(self):
        from linework.storage import read_layer
        from linework.native_brush import point_thickness
        strokes = read_layer(self.doc,self.layer)
        diameters = [point_thickness(strokes[0],i) for i in range(len(strokes[0].points))]
        assert all(math.isclose(d,11) for d in diameters), (diameters, self.c.status.text())
        self.result['animated_autosave_allows_thickness_edit'] = 'pass'
        self.k.action('edit_undo').trigger(); self.doc.waitForDone(); self.c.poll()
        assert [s.data() for s in read_layer(self.doc,self.layer)] == self.expected
        self.result['animated_autosave_native_undo_preserves_editability'] = 'pass'
        self.doc.setModified(False); self.source_doc.setModified(False)
        self.window.qwindow().grab().save(str(ROOT/'docs/images/autosave-recovery.png'))
        self.result['result'] = 'pass'; self.finish()


Krita.instance().addExtension(Probe(Krita.instance()))
