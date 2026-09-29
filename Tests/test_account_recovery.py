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
            navigation=account_page(Catalog(),'x',index_only=True)['items']
            self.assertEqual([e['id'] for e in navigation],['q','new'])
            self.assertEqual([e['offset'] for e in navigation],[0,1])
            self.assertEqual([e['id'] for e in account_page(Catalog(),'x',branch='old',index_only=True)['items']],['q','old'])
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

class LibraryStateTests(unittest.TestCase):
    def test_rename_archive_restore_are_local_and_searchable(self):
        import tempfile
        from account_recovery import update_library,library_page,apply_library_state
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            class Catalog:
                data=Path(tmp)
                sessions={'a':{'id':'a','title':'Original','review':''}}
                def get(self,key):return self.sessions[key]
                def list(self,**params):return {'items':list(self.sessions.values())}
            c=Catalog()
            update_library(c,'a',title='Local title',archived=True)
            self.assertEqual(library_page(c,{})['total'],0)
            self.assertEqual(library_page(c,{'scope':'archived'})['items'][0]['title'],'Local title')
            c.sessions['a']['title']='Original';apply_library_state(c)
            self.assertEqual(c.sessions['a']['title'],'Local title')
            update_library(c,'a',archived=False)
            self.assertEqual(library_page(c,{})['total'],1)

    def test_missing_chat_bodies_are_grouped_without_mutation(self):
        from account_recovery import library_page
        class Catalog:
            sessions={str(i):row for i,row in enumerate([
                {'id':'empty','source':'account','content_available':False,'review':'useful'},
                {'id':'full','source':'account','content_available':True},
                {'id':'code','source':'code','content_available':False}])}
            def list(self,**params):return {'items':list(self.sessions.values())}
        catalog=Catalog()
        self.assertEqual([r['id'] for r in library_page(catalog,{})['items']],['full','code'])
        self.assertEqual(library_page(catalog,{'scope':'starred'})['total'],0)
        self.assertEqual([r['id'] for r in library_page(catalog,{'scope':'missing'})['items']],['empty'])
        self.assertEqual(len(catalog.sessions),3)
        self.assertNotIn('local_archived',catalog.sessions['0'])

    def test_artifact_preview_returns_exact_version_source(self):
        import tempfile,zipfile,json
        from account_recovery import artifacts
        with tempfile.TemporaryDirectory() as tmp:
            html='<button onclick="this.textContent=42">Click</button>'
            with zipfile.ZipFile(Path(tmp)/'frames-000.zip','w') as z:
                z.writestr('artifacts/a/artifact.json',json.dumps({'id':'a','active_version':'v','versions':[{'id':'v','title':'Saved'}]}))
                z.writestr('artifacts/a/versions/v.html',html)
            self.assertEqual(artifacts(Path(tmp),'a',html_preview=True)['html'],html)
