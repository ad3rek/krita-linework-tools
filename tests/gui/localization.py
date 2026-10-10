# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify the selected Krita interface language in native tools and options."""
import json, os, traceback
from pathlib import Path
from krita import Krita, Extension
from linework.qt import QApplication, QTimer, QDialog, QDockWidget, QAbstractButton, QCoreApplication
from linework.i18n import tr, language, resolve_language, CATALOGS
ROOT = Path(os.environ['LINEWORK_TEST_ROOT']).resolve()
class Probe(Extension):
    def setup(self): self.result = {}; self.after(self.start,1800)
    def createActions(self,w): pass
    def after(self,fn,ms=200): QTimer.singleShot(ms, lambda:self.safe(fn))
    def safe(self,fn):
        try: fn()
        except Exception:
            self.result.update(result='fail',traceback=traceback.format_exc()); self.finish()
    def finish(self):
        (ROOT/'docs/validation/localization.json').write_text(json.dumps(self.result,indent=2,ensure_ascii=False))
        for d in Krita.instance().documents(): d.setModified(False)
        if hasattr(self,'window'): self.window.qwindow().close()
        QTimer.singleShot(300,QApplication.instance().quit)
    def start(self):
        k=Krita.instance()
        for w in QApplication.topLevelWidgets():
            if w.metaObject().className()=='KisAutoSaveRecoveryDialog': QDialog.reject(w)
        if not k.activeDocument(): self.after(self.start); return
        self.window=k.activeWindow();self.window.activate();QApplication.setActiveWindow(self.window.qwindow())
        expected=resolve_language(os.environ['LINEWORK_TEST_LANGUAGE'],{p.stem for p in CATALOGS.glob('*.json')})
        assert language()==expected,(language(),expected,QCoreApplication.applicationName())
        from linework.tools import select_tool,current_controller,TOOL_IDS
        select_tool(4); self.c=current_controller(self.window);self.c.poll()
        self.window.qwindow().resize(1450,1020)
        self.dock=self.window.qwindow().findChild(QDockWidget,'sharedtooldocker')
        self.dock.show();self.dock.raise_()
        assert self.c.tool_label.text()==tr('Linework Thickness')
        assert self.c.groups['pressure'].header.text()==tr('Thickness')
        assert self.c.selection_mode.itemText(0)==tr('Points and strokes')
        assert self.c.apply_brush_button.text()==tr('Apply brush')
        for ident,source in zip(TOOL_IDS,('Linework Brush','Linework Curve','Linework Line','Linework Edit','Linework Thickness','Linework Erase')):
            button=self.window.qwindow().findChild(QAbstractButton,ident)
            assert button and tr(source) in button.toolTip(),(ident,button.toolTip() if button else None,tr(source))
        self.result.update(language=language(),krita=k.version(),tool_titles_options_and_actions='pass',
                           layout_direction=int(getattr(QApplication.layoutDirection(),'value',QApplication.layoutDirection())))
        self.after(self.capture)
    def capture(self):
        assert self.dock.isVisible() and self.c.groups['pressure'].header.isVisible()
        self.window.qwindow().grab().save(str(ROOT/'docs/images/localized-options.png'))
        self.result['result']='pass';self.finish()
Krita.instance().addExtension(Probe(Krita.instance()))
