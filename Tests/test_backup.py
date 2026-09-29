import json, tempfile, unittest
from pathlib import Path
import sys, zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Engine'))
from native_backup import Snapshot,describe,destination_info,source_files
from import_core import sha256

class BackupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.source=self.base/'source';self.dest=self.base/'destination';self.dest.mkdir();(self.source/'projects/p/subagents').mkdir(parents=True);(self.source/'projects/p/session.jsonl').write_text('{"type":"user","sessionId":"s","cwd":"/demo","message":{"content":"hello"}}\n');(self.source/'projects/p/subagents/agent-a.jsonl').write_text('{}\n');(self.source/'file-history/u').mkdir(parents=True);(self.source/'file-history/u/version').write_text('code');(self.source/'history.jsonl').write_text('{}\n');(self.source/'credentials.json').write_text('never copy');(self.source/'projects/p/skills').mkdir();(self.source/'projects/p/skills/secret.jsonl').write_text('not a chat')
 def test_allowlist_snapshot_hash_and_exclusions(self):
  self.assertEqual(describe(self.source)['sessions'],1)
  snap=Snapshot([str(self.source)],str(self.dest));snap.run();self.assertEqual(snap.state['status'],'completed');manifest=json.loads((snap.root/'code/manifest.json').read_text());self.assertEqual(len(manifest['files']),4)
  for entry in manifest['files']:self.assertEqual(sha256(snap.root/'code'/entry['path']),entry['sha256'])
  self.assertFalse((snap.root/'code/credentials.json').exists());self.assertEqual((self.source/'credentials.json').read_text(),'never copy')
 def test_overlap_symlink_and_invalid_zip(self):
  with self.assertRaises(ValueError):destination_info(self.source,[str(self.source)])
  (self.source/'projects/p/link.jsonl').symlink_to(self.source/'credentials.json');self.assertNotIn('code/projects/p/link.jsonl',[rel for _,rel in source_files(self.source)])
  bad=self.base/'conversations-000.zip';bad.write_text('HTML');snap=Snapshot([str(bad)],str(self.dest));snap.run();self.assertEqual(snap.state['status'],'partial');self.assertEqual(snap.state['completed'],0)
 def test_cancel_resume_and_conflict_preservation(self):
  snap=Snapshot([str(self.source)],str(self.dest));snap.cancel.set();snap.run();self.assertEqual(snap.state['status'],'cancelled');resumed=Snapshot(resume=str(snap.root));resumed.run();self.assertEqual(resumed.state['status'],'completed');target=snap.root/'code/projects/p/session.jsonl';target.write_text('changed by user');again=Snapshot(resume=str(snap.root));again.run();self.assertEqual(again.state['status'],'partial');self.assertEqual(target.read_text(),'changed by user')
 def test_zip_kept_and_unique_batches(self):
  archive=self.base/'conversations-000.zip'
  with zipfile.ZipFile(archive,'w') as z:z.writestr('conversations.json','[]')
  a=Snapshot([str(archive)],str(self.dest));a.run();b=Snapshot([str(archive)],str(self.dest));b.run();self.assertNotEqual(a.root,b.root);self.assertEqual(sha256(archive),sha256(a.root/'account/conversations-000.zip'))
if __name__=='__main__':unittest.main()

class FailureTests(unittest.TestCase):
 setUp = BackupTests.setUp
 def test_space_and_missing_source_are_not_complete(self):
  from unittest.mock import patch
  from collections import namedtuple
  Usage=namedtuple('Usage','total used free')
  with patch('native_backup.shutil.disk_usage',return_value=Usage(100,99,1)):
   with self.assertRaisesRegex(ValueError,'空间'):Snapshot([str(self.source)],str(self.dest))
  snapshot=Snapshot([str(self.source)],str(self.dest));(self.source/'history.jsonl').unlink();snapshot.run();self.assertEqual(snapshot.state['status'],'partial');self.assertTrue(snapshot.state['errors'])
 def test_changing_source_requires_retry(self):
  from unittest.mock import patch
  import native_backup
  real=native_backup.sha256
  def changing(path):
   digest=real(path)
   if str(path).endswith('.copying'):
    src=self.source/'projects/p/session.jsonl';src.write_text(src.read_text()+'{}\n')
   return digest
  snapshot=Snapshot([str(self.source)],str(self.dest))
  with patch('native_backup.sha256',side_effect=changing):snapshot.run()
  self.assertEqual(snapshot.state['status'],'partial');self.assertTrue(any('持续变化' in e['error'] for e in snapshot.state['errors']))
