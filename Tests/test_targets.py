import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Engine'))
from account_recovery import library_page
from claude_bridge import create_session, detect_claude, session_command
from import_core import sha256
from native_backup import Snapshot
from native_server import NativeService
from target_imports import import_to_target, load_records, reconcile_targets, selection


FAKE_CLI = f'#!/usr/bin/env -S {shlex.quote(sys.executable)}\n' + '''
import json, os, pathlib, sys, time, uuid
args=sys.argv[1:]
root=pathlib.Path(os.environ['FAKE_CLAUDE_ROOT'])
mode=(root/'mode').read_text() if (root/'mode').exists() else ''
if args==['--version']:
 print('2.1.284' if mode=='old' else '2.1.285 (Claude Code)');sys.exit(0)
if args==['auth','status','--json']:
 print(json.dumps({'loggedIn':mode!='logout','configDirectory':str(root),'email':'never expose this'}));sys.exit(1 if mode=='logout' else 0)
with (root/'calls.jsonl').open('a') as f:f.write(json.dumps({'args':args,'cwd':os.getcwd()})+'\\n')
sid=args[args.index('--session-id')+1] if '--session-id' in args else str(uuid.uuid4())
assert '--safe-mode' in args and '--restricted' in args and '--strict-mcp-config' in args
assert json.loads(args[args.index('--settings')+1])['disableAllHooks']
assert args[args.index('--disallowedTools')+1]=='mcp__*'
assert args[args.index('--permission-mode')+1]=='dontAsk'
prompt=sys.stdin.read()
print(json.dumps({'type':'system','subtype':'init','session_id':sid}),flush=True)
if mode=='timeout':time.sleep(10)
if mode=='error':
 print(json.dumps({'type':'result','session_id':sid,'subtype':'error_during_execution','is_error':True}),flush=True);sys.exit(1)
dest=root/'projects'/'test project'/f'{sid}.jsonl';dest.parent.mkdir(parents=True,exist_ok=True)
history=pathlib.Path(args[args.index('--resume')+1]).read_text() if '--resume' in args else ''
dest.write_text(history+'\\n'+json.dumps({'type':'user','sessionId':sid,'message':{'content':prompt}})+'\\n'+json.dumps({'type':'assistant','sessionId':sid,'message':{'content':'ready'}})+'\\n')
print(json.dumps({'type':'result','session_id':sid,'subtype':'success','is_error':False}),flush=True)
'''


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="archive ' $(never) ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        source = self.base / 'source'
        (source / 'projects/p').mkdir(parents=True)
        self.project = self.base / 'project with spaces'; self.project.mkdir()
        self.original_id = str(uuid.uuid4())
        records = [dict(type=role, sessionId=self.original_id, cwd=str(self.project), uuid=str(uuid.uuid4()),
                        message={'role':role,'content':body}) for role,body in [('user','old question'),('assistant','old answer')]]
        (source / 'projects/p' / f'{self.original_id}.jsonl').write_text('\n'.join(json.dumps(r) for r in records)+'\n')
        self.long_text = '完整正文🙂\n' * 8000
        conversations = [{'uuid':'branched','name':'Branch title','chat_messages':[
            {'uuid':'q','sender':'human','text':'question','created_at':'2026-09-01T00:00:00Z'},
            {'uuid':'old','parent_message_uuid':'q','sender':'assistant','text':'OLD ANSWER','created_at':'2026-09-02T00:00:00Z'},
            {'uuid':'new','parent_message_uuid':'q','sender':'assistant','text':self.long_text,'created_at':'2026-09-03T00:00:00Z',
             'attachments':[{'file_name':'data.txt','extracted_content':'完整附件🙂'}, {'file_name':'lost.png'}]}]},
            {'uuid':'empty','chat_messages':[]}]
        with zipfile.ZipFile(source / 'conversations-000.zip','w') as archive:
            archive.writestr('conversations.json',json.dumps(conversations))
        dest=self.base/'out';dest.mkdir();snapshot=Snapshot([str(source)],str(dest));snapshot.run()
        self.service=NativeService();self.service.open_archive({'path':str(snapshot.root)})
        self.catalog=self.service.archive
        self.chat=next(r for r in self.catalog.sessions.values() if r['source']=='account' and r['content_available'])
        self.code=next(r for r in self.catalog.sessions.values() if r['source']=='code')
        self.config=self.base/'claude config';self.config.mkdir()
        self.cli=self.base/'fake claude';self.cli.write_text(FAKE_CLI);self.cli.chmod(0o700)
        env=patch.dict(os.environ,{'CLAUDE_ARCHIVE_CLAUDE':str(self.cli),'FAKE_CLAUDE_ROOT':str(self.config)})
        env.start();self.addCleanup(env.stop)

    def calls(self):
        path=self.config/'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def wait(self, job):
        for _ in range(500):
            if self.service.jobs[job]['status']!='running':return self.service.jobs[job]
            time.sleep(.01)
        self.fail('job did not finish')

    def test_chat_handoff_full_text_attachments_branch_and_dedup(self):
        source_hash=sha256(self.catalog.account_dir/'conversations-000.zip')
        result=import_to_target(self.catalog,self.chat['id'],'claude_chat')
        text=Path(result['transcript']).read_text()
        self.assertIn(self.long_text,text);self.assertNotIn('OLD ANSWER',text)
        self.assertIn('完整附件🙂',text);self.assertIn('lost.png',text)
        self.assertEqual(result['branch'],'new');self.assertEqual(result['status'],'prepared')
        self.assertEqual(import_to_target(self.catalog,self.chat['id'],'claude_chat')['directory'],result['directory'])
        old=import_to_target(self.catalog,self.chat['id'],'claude_chat','old')
        self.assertIn('OLD ANSWER',Path(old['transcript']).read_text());self.assertNotIn(self.long_text,Path(old['transcript']).read_text())
        self.assertEqual(sha256(self.catalog.account_dir/'conversations-000.zip'),source_hash)
        self.assertFalse(self.calls())
        Path(result['transcript']).write_text('edited material')
        new=import_to_target(self.catalog,self.chat['id'],'claude_chat')
        self.assertNotEqual(new['directory'],result['directory']);self.assertEqual(Path(result['transcript']).read_text(),'edited material')

    def test_native_code_fork_preserves_archive_and_persists_real_id(self):
        original=Path(self.code['source_path']).read_bytes()
        result=import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertNotEqual(result['session_id'],self.original_id)
        self.assertEqual(Path(self.code['source_path']).read_bytes(),original)
        self.assertEqual((Path(result['directory'])/'source.jsonl').read_bytes(),original)
        self.assertIn('old answer',Path(result['session_path']).read_text())
        args=self.calls()[0]['args'];self.assertIn('--fork-session',args)
        self.assertEqual(args[args.index('--tools')+1],'')
        self.assertEqual(args[args.index('--resume')+1],str(Path(result['directory'])/'source.jsonl'))
        self.assertEqual(self.calls()[0]['cwd'],str(self.project))
        tokens=shlex.split(result['resume_command']);self.assertEqual(tokens[1],str(self.project));self.assertEqual(tokens[3],str(self.cli))
        again=import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertEqual(again['session_id'],result['session_id']);self.assertEqual(len(self.calls()),1)
        Path(result['session_path']).unlink()
        with self.assertRaisesRegex(ValueError,'核对'):import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertEqual(len(self.calls()),1)

    def test_account_code_creation_read_only_and_destination_independence(self):
        self.chat.update(status='present',destination_thread_id='codex-thread')
        with patch.object(self.catalog,'reconcile'):
            job=self.wait(self.service.import_batch([self.chat['id']],'claude_code')['job_id'])
        self.assertFalse(job['errors']);result=job['results'][0]
        args=self.calls()[0]['args'];self.assertNotIn('--resume',args)
        self.assertEqual(args[args.index('--tools')+1],'Read')
        self.assertEqual(args[args.index('--session-id')+1],result['session_id'])
        self.assertEqual(self.calls()[0]['cwd'],result['directory'])
        self.assertEqual(job['entries'][self.chat['id']]['session_id'],result['session_id'])
        import_to_target(self.catalog,self.chat['id'],'claude_chat')
        reconcile_targets(self.catalog)
        self.assertEqual(self.chat['imports']['codex']['status'],'present')
        self.assertEqual(self.chat['imports']['claude_code']['status'],'present')
        self.assertEqual(self.chat['imports']['claude_chat']['status'],'prepared')
        self.assertFalse((self.catalog.data/'imports.json').exists())

    def test_failure_saves_id_and_retry_never_launches_again(self):
        (self.config/'mode').write_text('error')
        job=self.wait(self.service.import_batch([self.code['id']],'claude_code')['job_id'])
        self.assertEqual(len(job['errors']),1)
        record=next(iter(load_records(self.catalog).values()))
        self.assertEqual(record['status'],'needs_review');self.assertTrue(record['session_id'])
        self.assertEqual(job['entries'][self.code['id']]['session_id'],record['session_id'])
        with self.assertRaisesRegex(ValueError,'核对'):import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertEqual(len(self.calls()),1)
        opened=NativeService();jobs=opened.open_archive({'path':str(self.service.root)})['jobs']
        self.assertEqual(jobs[0]['destination'],'claude_code');self.assertEqual(jobs[0]['entries'],job['entries'])

    def test_timeout_and_cancel_persist_initial_session_id(self):
        artifact=import_to_target(self.catalog,self.chat['id'],'claude_chat')
        record={**artifact,'cwd':artifact['directory'],'executable':str(self.cli),'session_id':str(uuid.uuid4())}
        (self.config/'mode').write_text('timeout')
        updates=[]
        with self.assertRaisesRegex(RuntimeError,'超时'):
            create_session(self.chat,record,lambda:updates.append(dict(record)),timeout=.2)
        self.assertTrue(any(r.get('launched') for r in updates));self.assertTrue(record['session_id'])
        cancel=threading.Event();cancel.set()
        with self.assertRaisesRegex(RuntimeError,'中断'):create_session(self.chat,record,lambda:None,cancel=cancel)

    def test_missing_body_hash_changes_and_invalid_request_do_not_launch(self):
        empty=next(r for r in self.catalog.sessions.values() if r['source']=='account' and not r['content_available'])
        for row,branch in [(empty,''),(self.chat,'all'),(self.chat,'unknown')]:
            with self.assertRaises(ValueError):import_to_target(self.catalog,row['id'],'claude_code',branch)
        Path(self.code['source_path']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'变化'):import_to_target(self.catalog,self.code['id'],'claude_code')
        with self.assertRaises(ValueError):self.service.import_batch([])
        with self.assertRaises(ValueError):self.service.import_batch([self.chat['id']],'unknown')
        self.assertFalse(self.service.jobs);self.assertFalse(self.calls())

    def test_detection_missing_old_logged_out_never_creates_session(self):
        self.assertEqual(detect_claude('/missing')['interface'],'未安装 Claude Code')
        for mode,expected in [('old','需要'),('logout','登录')]:
            (self.config/'mode').write_text(mode)
            result=detect_claude(str(self.cli));self.assertIn(expected,result['interface'])
            self.assertNotIn('email',result)
            with self.assertRaises(ValueError):import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertFalse(self.calls());self.assertFalse(load_records(self.catalog))

    def test_filter_by_destination_and_changed_status(self):
        import_to_target(self.catalog,self.chat['id'],'claude_chat')
        self.assertEqual(library_page(self.catalog,{'destination':'claude_chat','status':'prepared'})['total'],1)
        self.assertEqual(library_page(self.catalog,{'destination':'claude_code','status':'prepared'})['total'],0)
        self.assertEqual(library_page(self.catalog,{'destination':'codex','status':'present'})['total'],0)
        self.chat['sha256']='new-hash';reconcile_targets(self.catalog)
        self.assertEqual(self.chat['imports']['claude_chat']['status'],'changed')

    def test_legacy_codex_jobs_and_records_stay_compatible(self):
        legacy={'legacy-key':{'thread_id':'legacy-thread','status':'completed'}}
        (self.catalog.data/'imports.json').write_text(json.dumps(legacy))
        import_to_target(self.catalog,self.chat['id'],'claude_chat')
        self.assertEqual(json.loads((self.catalog.data/'imports.json').read_text()),legacy)
        with patch('codex_bridge.make_account_context_thread',return_value={'status':'completed','thread_id':'new-thread'}) as create:
            job=self.wait(self.service.import_batch([self.chat['id']])['job_id'])
        create.assert_called_once();self.assertEqual(job['destination'],'codex')
        self.assertEqual(job['results'][0]['thread_id'],'new-thread')

    def test_ambiguous_crash_before_cli_id_blocks_duplicate_fork(self):
        def crash(row,record,persist,cancel):
            record.update(status='creating',launched=True);persist();raise RuntimeError('crashed before init')
        with patch('claude_bridge.create_session',side_effect=crash):
            with self.assertRaises(RuntimeError):import_to_target(self.catalog,self.code['id'],'claude_code')
        with patch('claude_bridge.create_session') as create:
            with self.assertRaisesRegex(ValueError,'核对'):import_to_target(self.catalog,self.code['id'],'claude_code')
            create.assert_not_called()

    def test_journalled_success_recovers_without_another_cli_call(self):
        result=import_to_target(self.catalog,self.code['id'],'claude_code')
        path=self.catalog.data/'target-imports.json'
        records=json.loads(path.read_text());record=next(iter(records.values()))
        record['status']='creating';record.pop('resume_command');path.write_text(json.dumps(records))
        with patch('claude_bridge.create_session') as create:
            recovered=import_to_target(self.catalog,self.code['id'],'claude_code')
        create.assert_not_called();self.assertEqual(recovered['session_id'],result['session_id'])
        self.assertEqual(recovered['status'],'existing');self.assertTrue(recovered['resume_command'])
        self.assertEqual(len(self.calls()),1)

    def test_invalid_cache_empty_branch_and_zero_exit_without_success_are_rejected(self):
        raw=Path(self.chat['raw_cache_file']);original=raw.read_bytes()
        raw.write_text('{}')
        with self.assertRaisesRegex(ValueError,'缓存'):import_to_target(self.catalog,self.chat['id'],'claude_chat')
        raw.write_bytes(original)
        # Valid file, but branch body has no recoverable content.
        with patch('target_imports.account_selection',return_value=('empty',[])):
            with self.assertRaisesRegex(ValueError,'正文'):import_to_target(self.catalog,self.chat['id'],'claude_code')
        self.cli.write_text(FAKE_CLI.replace("'subtype':'success','is_error':False", "'subtype':'error_max_turns','is_error':True"))
        with self.assertRaisesRegex(RuntimeError,'失败'):import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertEqual(next(iter(load_records(self.catalog).values()))['status'],'needs_review')

    def test_default_model_retained_without_loading_hooks_or_plugins(self):
        (self.config/'settings.json').write_text(json.dumps({'model':'sonnet','hooks':{'secret':'never load'},'enabledPlugins':{'secret':True}}))
        result=import_to_target(self.catalog,self.chat['id'],'claude_code')
        args=self.calls()[0]['args'];settings=json.loads(args[args.index('--settings')+1])
        self.assertEqual(settings,{'disableAllHooks':True,'model':'sonnet'})
        self.assertEqual(args[args.index('--name')+1],'档案 · Branch title')
        self.assertTrue(result['session_path'])

    def test_busy_service_and_interrupted_job_keep_destination_and_branch(self):
        self.service.jobs['busy']={'status':'running'}
        with self.assertRaisesRegex(ValueError,'等待'):self.service.import_batch([self.chat['id']],'claude_chat')
        self.service.jobs={}
        job=self.wait(self.service.import_batch([self.chat['id']],'claude_chat',{self.chat['id']:'old'})['job_id'])
        self.assertEqual(job['results'][0]['branch'],'old')
        path=self.catalog.data/'native-import-jobs.json';data=json.loads(path.read_text())
        next(iter(data.values()))['status']='running';path.write_text(json.dumps(data))
        reopened=NativeService();restored=reopened.open_archive({'path':str(self.service.root)})['jobs'][0]
        self.assertEqual(restored['status'],'interrupted')
        self.assertEqual(restored['destination'],'claude_chat')
        self.assertEqual(restored['branches'],{self.chat['id']:'old'})

    def test_missing_project_uses_owned_directory_and_archive_hash_is_checked(self):
        self.project.rmdir()
        result=import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertEqual(self.calls()[0]['cwd'],result['directory'])
        archive=self.catalog.account_dir/'conversations-000.zip'
        with archive.open('ab') as output:output.write(b'changed')
        with self.assertRaisesRegex(ValueError,'ZIP'):import_to_target(self.catalog,self.chat['id'],'claude_chat')
        self.assertEqual(len(self.calls()),1)

    def test_damaged_destination_journal_does_not_block_reading_or_allow_import(self):
        (self.catalog.data/'target-imports.json').write_text('invalid json')
        self.catalog.reconcile()
        self.assertEqual(self.chat['imports']['claude_code']['status'],'needs_review')
        self.assertTrue(self.catalog.messages(self.chat['id'])['items'])
        with self.assertRaises(ValueError):import_to_target(self.catalog,self.chat['id'],'claude_chat')
        self.assertFalse(self.calls())

    def test_invalid_native_jsonl_is_not_silently_normalized(self):
        path=Path(self.code['source_path'])
        with path.open('a') as output:output.write('invalid json\n')
        self.code['sha256']=sha256(path)
        original=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'JSONL'):import_to_target(self.catalog,self.code['id'],'claude_code')
        self.assertEqual(path.read_bytes(),original)
        self.assertFalse(self.calls());self.assertFalse(load_records(self.catalog))


if __name__=='__main__':unittest.main()
