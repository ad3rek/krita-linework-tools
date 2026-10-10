# SPDX-License-Identifier: GPL-3.0-or-later
"""Loading annotations late and retrying busy native frame restoration."""
import ast,copy,json
from pathlib import Path
from types import SimpleNamespace
import unittest

class Busy(RuntimeError): pass

class BootstrapTests(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'linework/animation.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='bootstrap_layer')
        self.state={'animated':True,'owner':'image','node':'layer','frames':[{'time':0,'id':7,'editable':False}]}
        self.namespace={'_bootstrapped':set(),'_bootstrapping':set(),'AnimationBusy':Busy,
                        'tr':lambda s:s,'encoded':json.dumps}
        self.restore_hook=lambda:None
        self.calls=[]
        def call(name,*args):
            self.calls.append(name)
            if name=='info':return copy.deepcopy(self.state)
            if name=='restore':
                self.restore_hook()
                self.state['frames'][0]['editable']=True
            return {}
        self.namespace['call']=call
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),self.namespace)
        self.bootstrap=self.namespace['bootstrap_layer']
        self.doc=SimpleNamespace(waitForDone=lambda:None)
        self.saved={'kind':'animated','frames':{'0':{'strokes':[{'id':'test'}]}}}
    def test_late_annotation_still_restores_an_ordinary_animated_layer(self):
        self.bootstrap(self.doc,object(),{})
        self.assertFalse(self.namespace['_bootstrapped'])
        result=self.bootstrap(self.doc,object(),self.saved)
        self.assertTrue(result['frames'][0]['editable'])
        self.assertEqual(self.calls.count('restore'),1)
    def test_busy_restore_remains_retryable(self):
        self.restore_hook=lambda:(_ for _ in ()).throw(Busy())
        with self.assertRaises(Busy):self.bootstrap(self.doc,object(),self.saved)
        self.assertFalse(self.namespace['_bootstrapped'])
        self.assertFalse(self.namespace['_bootstrapping'])
        self.restore_hook=lambda:None
        self.assertTrue(self.bootstrap(self.doc,object(),self.saved)['frames'][0]['editable'])
    def test_nested_stroke_end_callback_does_not_restore_recursively(self):
        def callback():
            with self.assertRaises(Busy):self.bootstrap(self.doc,object(),self.saved)
        self.restore_hook=callback
        self.bootstrap(self.doc,object(),self.saved)
        self.assertEqual(self.calls.count('restore'),1)
        self.assertFalse(self.namespace['_bootstrapping'])
        self.assertTrue(self.namespace['_bootstrapped'])

if __name__=='__main__':unittest.main()
