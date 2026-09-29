import unittest, tempfile, zipfile, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Engine'))
from native_backup import discover_sources
class DiscoveryTests(unittest.TestCase):
 def test_mixed_parent_dedup_and_exclusion(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);code=root/'backup/code';(code/'projects/p').mkdir(parents=True)
   (code/'projects/p/s.jsonl').write_text('{"type":"user","message":{"content":"hello"}}\n')
   account=root/'exports';account.mkdir()
   with zipfile.ZipFile(account/'conversations-000.zip','w') as z:z.writestr('conversations.json','[]')
   (root/'alias').symlink_to(code,target_is_directory=True)
   (root/'node_modules').mkdir();(root/'node_modules/alias').symlink_to(code,target_is_directory=True)
   result=discover_sources(root)
   self.assertEqual({s['kind'] for s in result['sources']},{'code','account'})
   self.assertEqual(len(result['sources']),2)
   self.assertEqual(discover_sources(code)['sources'][0]['sessions'],1)
 def test_invalid_and_empty(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'conversations-000.zip').write_text('<html>')
   result=discover_sources(root);self.assertFalse(result['sources']);self.assertTrue(result['warnings'])
   (root/'conversations-000.zip').unlink();(root/'projects/p').mkdir(parents=True);(root/'projects/p/other.jsonl').write_text('{}\n')
   self.assertFalse(discover_sources(root)['sources'])
 def test_bound_and_symlink(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'nested/deeper').mkdir(parents=True)
   self.assertTrue(discover_sources(root,max_depth=0)['warnings'])
   (root/'alias').symlink_to(root/'nested',target_is_directory=True)
   with self.assertRaises(ValueError):discover_sources(root/'alias')
