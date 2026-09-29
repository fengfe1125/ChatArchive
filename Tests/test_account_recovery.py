import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Engine'))
from archive_core import _account_message

class RecoveryTests(unittest.TestCase):
    def test_legacy_text_with_empty_blocks(self):
        result=_account_message({'sender':'assistant','content':[],'text':'saved answer'})
        self.assertIsNotNone(result)
        self.assertEqual(result['text'],'saved answer')

    def test_thinking_and_tool_records_have_reading_entries(self):
        result=_account_message({'sender':'assistant','content':[
            {'type':'thinking','thinking':'saved reasoning'},
            {'type':'tool_use','name':'create_file','input':{'path':'a.txt','content':'saved file'}},
            {'type':'tool_result','name':'create_file','content':[{'type':'text','text':'created'}]}]})
        self.assertIsNotNone(result)
        self.assertEqual(len(result['media']),3)
        self.assertIn('saved file',result['media'][1]['text'])

class StructureTests(unittest.TestCase):
    def test_branch_paths_do_not_mix_sibling_answers(self):
        from account_recovery import branch_paths
        messages=[{'uuid':'q','sender':'human'},
                  {'uuid':'a1','parent_message_uuid':'q','created_at':'2026-01-01'},
                  {'uuid':'a2','parent_message_uuid':'q','created_at':'2026-01-02'},
                  {'uuid':'q2','parent_message_uuid':'a1','created_at':'2026-01-03'}]
        self.assertEqual([p['nodes'] for p in branch_paths(messages)],[['q','a1','q2'],['q','a2']])

    def test_artifacts_all_versions_are_readable_without_scripts(self):
        from account_recovery import artifacts
        import tempfile,json,zipfile
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(Path(tmp)/'frames-000.zip','w') as z:
                z.writestr('artifacts/a/artifact.json',json.dumps({'id':'a','active_version':'v2','versions':[{'id':'v1','title':'Old'},{'id':'v2','title':'New'}]}))
                z.writestr('artifacts/a/versions/v1.html','<h1>Earlier draft</h1>')
                z.writestr('artifacts/a/versions/v2.html','<script>doNotRun()</script><p>Saved work</p>')
            self.assertEqual(len(artifacts(Path(tmp))['items'][0]['versions']),2)
            self.assertEqual(artifacts(Path(tmp),'a')['content'],'Saved work')
            self.assertEqual(artifacts(Path(tmp),'a','v1')['content'],'Earlier draft')

    def test_account_page_preserves_block_order_and_selected_branch(self):
        import tempfile,json
        from account_recovery import account_page
        from import_core import sha256
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'raw.json'
            path.write_text(json.dumps({'chat_messages':[
                {'uuid':'q','sender':'human','text':'question'},
                {'uuid':'old','parent_message_uuid':'q','sender':'assistant','created_at':'2026-01-01','text':'old answer'},
                {'uuid':'new','parent_message_uuid':'q','sender':'assistant','created_at':'2026-01-02','content':[
                    {'type':'text','text':'before'}, {'type':'tool_use','name':'test','input':{'x':1}}, {'type':'text','text':'after'}]}]}))
            class Catalog:
                def get(self,_):return {'source':'account','valid_hash':True,'raw_cache_file':str(path),'raw_cache_sha256':sha256(path)}
            result=account_page(Catalog(),'x')
            self.assertEqual(result['branch'],'new')
            self.assertEqual([m['text'] for m in result['items']],['question','before','','after'])
            old=account_page(Catalog(),'x',branch='old')
            self.assertEqual([m['text'] for m in old['items']],['question','old answer'])

class TitleTests(unittest.TestCase):
    def test_original_title_and_user_question_take_precedence(self):
        from account_recovery import conversation_title
        messages=[{'role':'assistant','text':'answer'}, {'role':'user','text':'My question'}]
        self.assertEqual(conversation_title({'name':'Original'},messages),'Original')
        self.assertEqual(conversation_title({},messages),'My question')

    def test_empty_exports_get_distinct_honest_labels(self):
        from account_recovery import conversation_title
        self.assertEqual(conversation_title({'uuid':'abcdef123','created_at':'2026-09-01T12:30:00Z'},[]),'对话 · 2026-09-01 12:30 · abcdef')
        messages=[{'role':'user','text':'','media':[{'name':'draft.txt','type':'file'}]}]
        self.assertIn('附件：draft.txt',conversation_title({'created_at':'2026-09-01'},messages))
