# SPDX-License-Identifier: GPL-3.0-or-later
"""Queued animation updates must not touch closing or unviewed documents."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

class FlushTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'linework/animation.py'
        node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='flush')
        node.body=[n for n in node.body if not isinstance(n,ast.ImportFrom)]
        self.callbacks=[];self.calls=[]
        self.visible=self.document('visible');self.closed=self.document('closed')
        app=SimpleNamespace(views=lambda:[SimpleNamespace(document=lambda:self.visible)],documents=lambda:[self.visible,self.closed])
        self.namespace={'_shutting_down':False,'_syncing':False,'_bootstrapping':set(),
                        '_pending':{'image'},'native_busy':lambda:False,
                        'CONTROLLERS':{},'sip':SimpleNamespace(isdeleted=lambda c:False),
                        'QTimer':SimpleNamespace(singleShot=lambda ms,fn:self.callbacks.append((ms,fn))),
                        'Krita':SimpleNamespace(instance=lambda:app),'AnimationBusy':type('Busy',(RuntimeError,),{}),
                        'bootstrap_document':lambda doc:self.calls.append(('bootstrap',doc)),
                        'sync_document':lambda doc:self.calls.append(('sync',doc))}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),self.namespace)
        self.flush=self.namespace['flush']
    @staticmethod
    def document(name):
        return SimpleNamespace(rootNode=lambda:SimpleNamespace(uniqueId=lambda:SimpleNamespace(toString=lambda:name)))
    def test_closed_document_is_not_bootstrapped(self):
        self.flush()
        self.assertEqual(self.calls,[('bootstrap',self.visible),('sync',self.visible)])
        self.assertFalse(self.namespace['_pending'])
        self.assertFalse(self.namespace['_syncing'])
    def test_window_close_defers_without_touching_documents(self):
        self.namespace['CONTROLLERS']={1:SimpleNamespace(_window_closing=True)}
        self.flush()
        self.assertFalse(self.calls)
        self.assertEqual(len(self.callbacks),1)
        self.assertEqual(self.callbacks[0][0],100)
        self.assertEqual(self.namespace['_pending'],{'image'})
    def test_cancelled_close_resumes_pending_update(self):
        controller=SimpleNamespace(_window_closing=True)
        self.namespace['CONTROLLERS']={1:controller}
        self.flush();controller._window_closing=False
        self.callbacks[0][1]()
        self.assertEqual(self.calls,[('bootstrap',self.visible),('sync',self.visible)])
        self.assertFalse(self.namespace['_pending'])

if __name__=='__main__':unittest.main()
