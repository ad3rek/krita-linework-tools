# SPDX-License-Identifier: GPL-3.0-or-later
"""Script actions must target the visible document's canvas controller."""
import ast,os
from pathlib import Path
from types import SimpleNamespace
import unittest
ROOT=Path(__file__).resolve().parents[1]
class ControllerSelectionTests(unittest.TestCase):
 def setUp(self):
  source=Path(os.environ.get('LINEWORK_TEST_SOURCE',ROOT))/'linework/tools.py'
  fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='current_controller')
  self.controllers={};self.window=SimpleNamespace(qwindow=lambda:'requested window')
  env={'CONTROLLERS':self.controllers,'sip':SimpleNamespace(isdeleted=lambda obj:getattr(obj,'deleted',False))}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),env);self.current=env['current_controller']
 def controller(self,name,visible=True,deleted=False,window='requested window',active=True):
  c=SimpleNamespace(_canvas=SimpleNamespace(isVisible=lambda:visible,deleted=deleted),_window=window,active=active)
  self.controllers[name]=c;return c
 def test_hidden_previous_document_does_not_take_script_actions(self):
  self.controller('hidden',visible=False);current=self.controller('visible')
  self.assertIs(self.current(self.window),current)
 def test_destroyed_canvas_is_skipped(self):
  self.controller('destroyed',deleted=True);current=self.controller('visible')
  self.assertIs(self.current(self.window),current)
 def test_other_windows_and_inactive_tools_are_skipped(self):
  self.controller('other',window='other window');self.controller('paused',active=False)
  current=self.controller('visible');self.assertIs(self.current(self.window),current)
 def test_no_visible_canvas_returns_none(self):
  self.controller('hidden',visible=False);self.assertIsNone(self.current(self.window))
if __name__=='__main__':unittest.main()
