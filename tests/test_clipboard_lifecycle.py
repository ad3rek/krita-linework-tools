# SPDX-License-Identifier: GPL-3.0-or-later
"""Clipboard callbacks may deliver native events or outlive their source view."""
import ast
import copy
import json
import logging
import math
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest


class Busy(RuntimeError):
    pass


class Mime:
    def __init__(self, payload=None):
        self.values = {'application/x-krita-node-internal-pointer':b'native'}
        if payload is not None:self.values['application/x-krita-linework-layers-v1']=json.dumps(payload).encode()
        self.deleted = False
        self.writes = 0
    def hasFormat(self, key):return key in self.values
    def data(self, key):return self.values[key]
    def setData(self, key, value):
        if self.deleted:raise RuntimeError('Deleted native MIME object')
        self.writes += 1;self.values[key] = value


class ClipboardLifecycleTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get('LINEWORK_TEST_SOURCE', Path(__file__).resolve().parents[1]))
        path = root/'linework/clipboard.py'
        body = [n for n in ast.parse(path.read_text()).body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.Assign))]
        self.callbacks = []
        self.mime = Mime()
        self.clipboard = SimpleNamespace(mimeData=lambda:self.mime)
        self.doc = SimpleNamespace(rootNode=lambda:object())
        self.view = SimpleNamespace(document=lambda:self.doc)
        self.window = SimpleNamespace(activeView=lambda:self.view)
        self.saved = {'source_id':'source','name':'Linework','type':'paintlayer',
                      'record':{'kind':'animated','geometry':[900,900,72,72],
                                'frames':{'0':{'geometry':[900,900,72,72],'strokes':[]}}},'children':[]}
        self.payload = {'version':1,'document_version':8,'layers':[copy.deepcopy(self.saved)]}
        self.node = SimpleNamespace(childNodes=lambda:[], name=lambda:'Linework')
        self.adopted = []
        namespace = {'__name__':'linework.clipboard', '__package__':'linework', 'copy':copy,
                     'json':json, 'logging':logging, 'math':math, 'time':time, 'QObject':object,
                     'QTimer':SimpleNamespace(singleShot=lambda ms,fn:self.callbacks.append(fn)),
                     'QByteArray':bytes, 'QApplication':SimpleNamespace(clipboard=lambda:self.clipboard),
                     'sip':SimpleNamespace(isdeleted=lambda obj:obj.deleted), 'AnimationBusy':Busy}
        exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)
        self.namespace = namespace
        self.obj = namespace['LayerClipboard'].__new__(namespace['LayerClipboard'])
        self.obj._capture = None;self.obj._pastes=[];self.obj._writing=False
        namespace.update(metadata=lambda doc:{'version':8,'layers':{'source':self.saved['record']}},
                         layer_id=lambda node:'source' if node is self.node else 'destination',
                         snapshot_node=lambda *args:copy.deepcopy(self.saved), walk=lambda node:[],
                         sync_document=lambda doc:None, encoded=lambda obj:json.dumps(obj).encode(),
                         call=lambda *args:None, selected_roots=lambda view:[self.node],
                         pair_nodes=lambda nodes,snapshots:[(object(),snapshots[0])],
                         restore_nodes=lambda doc,pairs,version:self.adopted.append(pairs) or True)
        import sys
        from unittest.mock import patch
        modules=patch.dict(sys.modules,{'krita':SimpleNamespace(Krita=SimpleNamespace(instance=lambda:SimpleNamespace(activeWindow=lambda:self.window)))})
        modules.start();self.addCleanup(modules.stop)

    def capture(self):
        self.obj._capture = (self.mime,self.doc,[self.node],time.monotonic()+10)
        return self.obj._capture

    def test_malformed_sidecar_does_not_escape_the_qt_callback(self):
        malformed = [dict(self.payload,layers=[{}]), dict(self.payload,layers=[42]),
                     dict(self.payload,document_version='invalid'),
                     dict(self.payload,layers=[dict(self.saved,children=None)]),
                     dict(self.payload,layers=[dict(self.saved,record=['invalid'])]),
                     dict(self.payload,layers=[dict(self.saved,record={'geometry':[900,900,0,72]})]),
                     dict(self.payload,layers=[dict(self.saved,record={'geometry':[900,900,float('inf'),72]})])]
        for payload in malformed:
            with self.subTest(payload=payload):
                self.mime=Mime(payload)
                self.obj.paste()
                self.assertFalse(self.obj._pastes)
                self.assertFalse(self.callbacks)

    def test_paste_waits_for_busy_copy_metadata(self):
        self.capture();self.obj.paste()
        self.assertEqual(len(self.obj._pastes),1)
        self.callbacks.pop(0)()
        self.assertFalse(self.adopted)
        self.mime.values[self.namespace['MIME']]=json.dumps(self.payload).encode()
        self.callbacks.pop(0)()
        self.assertEqual(len(self.adopted),1)
        self.assertFalse(self.obj._pastes)

    def test_waiting_paste_is_cancelled_if_clipboard_changes(self):
        self.capture();self.obj.paste()
        self.assertTrue(self.obj._pastes)
        self.mime=Mime()
        self.callbacks.pop(0)()
        self.assertFalse(self.adopted)
        self.assertFalse(self.obj._pastes)

    def test_event_delivery_during_restore_never_writes_to_stale_mime(self):
        capture=self.capture();original=self.mime
        def restore(*args):
            original.deleted=True;self.mime=Mime()
        self.namespace['call']=restore
        self.obj.enrich(capture)
        self.assertEqual(original.writes,0)
        self.assertIsNone(self.obj._capture)
        self.assertFalse(self.obj._writing)

    def test_closing_target_view_releases_pending_paste(self):
        self.mime=Mime(self.payload);self.obj.paste()
        self.view.document=lambda:(_ for _ in ()).throw(RuntimeError('View closed'))
        self.callbacks.pop(0)()
        self.assertFalse(self.obj._pastes)
        self.assertFalse(self.adopted)

    def test_closing_target_view_cancels_copy_metadata_wait(self):
        self.capture();self.obj.paste()
        self.view.document=lambda:None
        self.callbacks.pop(0)()
        self.assertFalse(self.obj._pastes)
        self.assertFalse(self.callbacks)


if __name__=='__main__':unittest.main()
