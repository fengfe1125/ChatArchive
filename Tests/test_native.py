import json, tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Engine'))
from native_backup import Snapshot
from native_server import NativeService

class NativeTests(unittest.TestCase):
 def test_account_only_open_and_missing_body(self):
  import zipfile
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);source=base/'conversations-000.zip';dest=base/'out';dest.mkdir()
   with zipfile.ZipFile(source,'w') as z:z.writestr('conversations.json',json.dumps([{'uuid':'a','name':'empty','chat_messages':[]}]))
   snap=Snapshot([str(source)],str(dest));snap.run();service=NativeService();value=service.open_archive({'path':str(snap.root)})
   self.assertEqual(value['root'],str(snap.root));self.assertEqual(len(service.archive.sessions),1)
   row=next(iter(service.archive.sessions.values()));self.assertFalse(row['content_available'])
 def test_direct_open_workdata_separation_and_state_migration(self):
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);source=base/'source';source.mkdir();(source/'manifest.json').write_text('{"files":[]}');dest=base/'out';dest.mkdir();old=base/'old';old.mkdir();(old/'reviews.json').write_text('{"example":"useful"}')
   service=NativeService();opened=service.open_archive({'path':str(source),'workspace':str(dest)});service.migrate(str(old));self.assertTrue((Path(opened['root'])/'data/reviews.json').exists());self.assertEqual(set(p.name for p in source.iterdir()),{'manifest.json'})
 def test_detect_missing_executable_does_not_create_thread(self):
  from unittest.mock import patch
  service=NativeService()
  with patch('native_server.shutil.which',return_value=None),patch('native_server.os.access',return_value=False):
   result=service.detect('/does/not/exist');self.assertEqual(result['codex']['version'],'未安装');self.assertFalse(service.jobs)
if __name__=='__main__':unittest.main()

class RelocationTests(unittest.TestCase):
 def test_move_archive_with_missing_original_source(self):
  import zipfile,shutil
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);src=base/'conversations-000.zip';dest=base/'out';dest.mkdir()
   with zipfile.ZipFile(src,'w') as z:z.writestr('conversations.json',json.dumps([{'uuid':'a','name':'hi','chat_messages':[{'sender':'human','content':'portable'}]}]))
   snapshot=Snapshot([str(src)],str(dest));snapshot.run();first=NativeService();first.open_archive({'path':str(snapshot.root)});ids=list(first.archive.sessions)
   moved=base/'moved';shutil.move(snapshot.root,moved);src.unlink()
   second=NativeService();second.open_archive({'path':str(moved)});self.assertEqual(list(second.archive.sessions),ids);self.assertEqual(second.archive.messages(ids[0])['items'][0]['text'],'portable')

class ImportRecoveryTests(unittest.TestCase):
 def test_existing_thread_skips_and_missing_text_reports_without_creation(self):
  import time,zipfile
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);src=base/'conversations-000.zip';dest=base/'out';dest.mkdir()
   with zipfile.ZipFile(src,'w') as z:z.writestr('conversations.json',json.dumps([{'uuid':'existing','name':'saved','chat_messages':[{'sender':'human','content':'hello'}]},{'uuid':'empty','name':'empty','chat_messages':[]}]))
   snapshot=Snapshot([str(src)],str(dest));snapshot.run();service=NativeService();service.open_archive({'path':str(snapshot.root)})
   rows=list(service.archive.sessions.values());present=next(r for r in rows if r['content_available']);present.update(status='present',destination_thread_id='existing-thread')
   with patch.object(service.archive,'reconcile'),patch('codex_bridge.make_account_context_thread') as create:
    key=service.import_batch([r['id'] for r in rows])['job_id']
    for _ in range(100):
     if service.jobs[key]['status']=='completed':break
     time.sleep(.01)
    self.assertEqual(service.jobs[key]['results'][0]['status'],'skipped');self.assertEqual(len(service.jobs[key]['errors']),1);create.assert_not_called()
   journal=snapshot.root/'data/native-import-jobs.json';data=json.loads(journal.read_text());data[key]['status']='running';journal.write_text(json.dumps(data))
   reopened=NativeService();value=reopened.open_archive({'path':str(snapshot.root)});self.assertEqual(value['jobs'][0]['status'],'interrupted');self.assertEqual(value['jobs'][0]['ids'],[r['id'] for r in rows])
