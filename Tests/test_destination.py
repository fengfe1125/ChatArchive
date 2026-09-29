import os,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Engine'))
from native_backup import default_destination,destination_info,Snapshot
class DestinationTests(unittest.TestCase):
 def test_custom_codex_home_preview_and_backup(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'CODEX_HOME':d+'/codex'}):
   source=Path(d)/'source';(source/'projects/p').mkdir(parents=True)
   (source/'projects/p/s.jsonl').write_text('{"type":"user","message":{"content":"hello"}}\n')
   target=default_destination();self.assertEqual(target,(Path(d)/'codex/chat-archive').resolve())
   info=destination_info(target,[str(source)],allow_missing=True)
   self.assertFalse(target.exists());self.assertGreater(info['free'],0)
   task=Snapshot([str(source)],str(target));task.run()
   self.assertEqual(task.state['status'],'completed');self.assertFalse((Path(d)/'codex/sessions').exists())
 def test_overlap_rejected_before_creating(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'CODEX_HOME':d+'/source/codex'}):
   source=Path(d)/'source';source.mkdir()
   with self.assertRaises(ValueError):Snapshot([str(source)],str(default_destination()))
   self.assertFalse(default_destination().exists())
