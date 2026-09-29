import io,json,tempfile,unittest,zipfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Engine'))
from native_download import run,prepare,read_manifest,SafeRedirect
class Response(io.BytesIO):
 def __init__(self,data,kind='application/zip'):
  super().__init__(data);self.headers={'Content-Length':str(len(data)),'Content-Type':kind}
class DownloadTests(unittest.TestCase):
 def test_download_resume_and_hash(self):
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d);manifest=folder/'manifest.json';manifest.write_text(json.dumps({'data_files':[{'filename':'conversations-000.zip','export_url':'https://claude.ai/export/private-token'}]}))
   root,items=prepare(manifest,folder);blob=io.BytesIO()
   with zipfile.ZipFile(blob,'w') as z:z.writestr('conversations.json','[]')
   state={};run(root,items,state,lambda *a,**k:Response(blob.getvalue()))
   self.assertEqual(state['status'],'completed');self.assertEqual(len(state['files'][0]['sha256']),64)
   self.assertNotIn('private-token',(root/'download-state.json').read_text())
   run(root,items,state,lambda *a,**k:self.fail('verified file downloaded twice'))
   self.assertEqual(state['completed'],1)
 def test_html_failure_redaction_retry(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);items=[{'filename':'conversations-000.zip','export_url':'https://claude.ai/private-token'}];state={}
   run(root,items,state,lambda *a,**k:Response(b'<html>','text/html'))
   self.assertEqual(state['status'],'partial');self.assertFalse((root/'conversations-000.zip').exists());self.assertNotIn('private-token',json.dumps(state))
 def test_manifest_validation(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'manifest.json'
   for name,url in [('../evil.zip','https://claude.ai/x'),('conversations-000.zip','http://claude.ai/x'),('conversations-000.zip','https://evil.com/x')]:
    p.write_text(json.dumps({'data_files':[{'filename':name,'export_url':url}]}))
    with self.assertRaises(ValueError):read_manifest(p)
 def test_redirect_block(self):
  with self.assertRaises(ValueError):SafeRedirect().redirect_request(None,None,302,'',{},'http://127.0.0.1/x')
