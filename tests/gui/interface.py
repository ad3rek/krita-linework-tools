# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect native Tool Options at narrow widths and with dark/light palettes."""
import json, os, traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QTimer, Qt
from linework.qt import QApplication, QDialog, QDockWidget, QScrollArea, QStyleFactory

ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()


class Probe(Extension):
    def setup(self):
        self.result = {}; self.after(self.start, 1800)

    def createActions(self, window): pass

    def after(self, fn, delay=150): QTimer.singleShot(delay, lambda: self.safe(fn))

    def safe(self, fn):
        try: fn()
        except Exception:
            self.result.update(result='fail', traceback=traceback.format_exc()); self.finish()

    def finish(self):
        (ROOT/'docs/validation/interface.json').write_text(json.dumps(self.result, indent=2))
        for doc in Krita.instance().documents(): doc.setModified(False)
        if hasattr(self, 'window'): self.window.qwindow().close()
        QTimer.singleShot(300, QApplication.instance().quit)

    def start(self):
        self.k = Krita.instance()
        for widget in QApplication.topLevelWidgets():
            if widget.metaObject().className() == 'KisAutoSaveRecoveryDialog': QDialog.reject(widget)
        if not self.k.activeDocument(): self.after(self.start); return
        self.window = self.k.activeWindow(); self.window.activate()
        QApplication.setActiveWindow(self.window.qwindow()); self.window.qwindow().resize(1450, 1020)
        self.doc = self.window.activeView().document()
        from linework.tools import select_tool, current_controller
        from linework.model import Point, Stroke
        from linework.storage import write_layer
        select_tool(3); self.c = current_controller(self.window)
        layer = self.c.create_native_layer(self.doc)
        self.strokes = [Stroke([Point(120,180,.5),Point(280,130,1),Point(430,220,.7)],width=18),
                        Stroke([Point(140,330),Point(400,400)],width=12,color='#287590')]
        write_layer(self.doc, layer, self.strokes)
        self.layer = layer
        self.result['written_binding'] = self.edit_state()
        self.dock = self.window.qwindow().findChild(QDockWidget, 'sharedtooldocker')
        self.dock.show(); self.dock.raise_()
        self.window.qwindow().resizeDocks([self.dock], [290], Qt.Orientation.Horizontal)
        self.window.qwindow().resizeDocks([self.dock], [700], Qt.Orientation.Vertical)
        self.mode = 0; self.after(self.show_mode)

    def show_mode(self):
        from linework.tools import select_tool, current_controller
        select_tool(self.mode); self.c = current_controller(self.window); self.c.poll()
        if self.mode in (3, 4):
            self.result['edit_binding_before_selection'] = self.edit_state()
            self.c.overlay.selection.set_points([(self.strokes[0].uid,1),(self.strokes[1].uid,0)])
            self.c.overlay.selectedChanged.emit()
        if self.mode == 0: self.c.smoothing.mode.setCurrentIndex(3)
        self.after(self.capture_mode)

    def capture_mode(self):
        areas = self.dock.findChildren(QScrollArea)
        assert areas and all(a.horizontalScrollBar().maximum() == 0 for a in areas)
        assert self.c.parent() is not None and self.dock.isVisible()
        name = ('brush','curve','line','edit','thickness','eraser')[self.mode]
        self.dock.grab().save(str(ROOT/'docs/images'/('options-'+name+'.png')))
        if self.mode == 3:
            self.result['edit_binding_after_selection'] = self.edit_state()
            assert self.c.thickness.isVisible() and self.c.thickness.isEnabled()
            self.window.qwindow().grab().save(str(ROOT/'docs/images/options-in-krita.png'))
            before = self.c.thickness.value()
            self.c.groups['pressure'].header.click()
            assert not self.c.thickness.isVisible()
            self.c.groups['pressure'].header.click()
            assert self.c.thickness.isVisible() and self.c.thickness.value() == before
            self.result['collapse_preserves_edit_values'] = 'pass'
        if self.mode == 5:
            assert self.c.eraser_size.isVisible() and not self.c.brush_group.isVisible()
            assert not self.c.eraser_strength.isVisible()
            self.c.eraser_mode.setCurrentIndex(1)
            assert self.c.eraser_strength.isVisible() and self.c.eraser_strength.isEnabled()
            self.c.eraser_mode.setCurrentIndex(0)
            assert not self.c.eraser_strength.isVisible()
            self.result['strength_shown_only_for_point_eraser'] = 'pass'
        self.result[name+'_narrow_native_options'] = 'pass'
        self.mode += 1
        if self.mode < 6: self.after(self.show_mode)
        else: self.after(self.light)

    def edit_state(self):
        active = self.doc.activeNode()
        overlay = self.c.overlay
        from linework.storage import metadata, layer_id
        return {'active': active.name() if active else None,
                'active_type': active.type() if active else None,
                'active_id': layer_id(active) if active else None,
                'written_id': layer_id(self.layer) if hasattr(self, 'layer') else None,
                'metadata': metadata(self.doc),
                'document': self.doc.rootNode().uniqueId().toString(),
                'view_document': self.c.current_view().document().rootNode().uniqueId().toString(),
                'layer': self.c.layer.name() if self.c.layer else None,
                'strokes': [s.uid for s in overlay.strokes] if overlay else None,
                'expected': [s.uid for s in self.strokes],
                'selection': [list(x) for x in overlay.selection.points] if overlay else None,
                'mode': self.c.mode, 'status': self.c.status.text()}

    def light(self):
        from linework.tools import select_tool, current_controller
        palette = QStyleFactory.create('Fusion').standardPalette()
        QApplication.setPalette(palette); self.window.qwindow().setPalette(palette)
        select_tool(3); self.c = current_controller(self.window); self.c.setPalette(palette); self.c.poll()
        self.c.overlay.selection.set_points([(self.strokes[0].uid,1)])
        self.c.overlay.selectedChanged.emit(); self.after(self.finish_light)

    def finish_light(self):
        self.dock.grab().save(str(ROOT/'docs/images/options-light.png'))
        assert self.c.groups['pressure'].header.palette().color(self.c.foregroundRole()) == self.c.palette().color(self.c.foregroundRole())
        self.result.update(theme_palette_inherited='pass', result='pass', krita=self.k.version())
        self.finish()


Krita.instance().addExtension(Probe(Krita.instance()))
