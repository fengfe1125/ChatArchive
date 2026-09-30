#!/usr/bin/env python3
"""Private localhost service owned by the native application."""
import json, os, secrets, shutil, subprocess, sys, threading, time, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from app import ImportService, make_handler
from archive_core import ArchiveCatalog
from archive_export import export_markdown
from import_core import BackupIndex, Staging, atomic_json
from native_backup import Snapshot, describe, destination_info, discover_sources, default_destination

class NativeService(ImportService):
    def __init__(self):
        self.token=secrets.token_urlsafe(32);self.jobs={};self.lock=threading.RLock()
        self.archive=None;self.index=None;self.staging=None;self.snapshots={};self.root=None;self.cancel_imports=threading.Event()
    def detect(self, executable='', claude=''):
        candidates=[executable,shutil.which('codex'),str(Path.home()/'.npm-global/bin/codex'),'/opt/homebrew/bin/codex','/usr/local/bin/codex']
        path=next((str(Path(p).expanduser()) for p in candidates if p and Path(p).expanduser().is_file() and os.access(Path(p).expanduser(),os.X_OK)),None)
        result={'path':path or '', 'version':'未安装','login':'待检查','interface':'待检查'}
        if path:
            os.environ['CLAUDE_ARCHIVE_CODEX']=path
            for args,key in [(['--version'],'version'),(['login','status'],'login')]:
                try:
                    response=subprocess.run([path,*args],capture_output=True,text=True,timeout=12)
                    if key=='version':result[key]=response.stdout.strip()[:100] if response.returncode==0 else '无法确认版本'
                    else:result[key]='已登录' if response.returncode==0 else '未登录或无法确认'
                except Exception:result[key]='检查超时或程序不可用'
            try:
                from codex_bridge import AppServer
                server=AppServer();server.close();result['interface']='可用'
            except Exception:result['interface']='接口未就绪，可继续备份与阅读'
        sources=[]
        for directory in {str(Path.home()/'.claude'),os.environ.get('CLAUDE_CONFIG_DIR','')}:
            if directory and Path(directory).is_dir():
                try:
                    item=describe(directory)
                    if item['files']:sources.append(item)
                except (OSError,ValueError):pass
        from claude_bridge import detect_claude
        claude_result=detect_claude(claude)
        if claude:os.environ['CLAUDE_ARCHIVE_CLAUDE']=str(Path(claude).expanduser())
        elif claude_result['path']:os.environ['CLAUDE_ARCHIVE_CLAUDE']=claude_result['path']
        return {'codex':result,'claude_code':claude_result,'sources':sources}
    def open_archive(self,body):
        if any(job['status']=='running' for job in self.jobs.values()):raise ValueError('请等待任务结束后切换档案')
        root=Path(body['path']).expanduser().resolve()
        if not root.is_dir():raise ValueError('档案磁盘未连接或目录不存在')
        if (root/'archive.json').is_file():
            config=json.loads((root/'archive.json').read_text())
        else:
            workspace=body.get('workspace')
            if not workspace:raise ValueError('首次打开旧备份，请选择独立的工作数据位置')
            source=root
            if not (source/'manifest.json').is_file():raise ValueError('不是已校验的 Code 备份目录')
            root=Path(workspace).resolve()/('聊天档案-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
            root.mkdir(mode=0o700)
            config={'format':1,'code':str(source),'account':body.get('account') or 'account','data':'data','status':'linked'}
            (root/'account').mkdir()
            atomic_json(root/'archive.json',config)
        if config.get('format')!=1:raise ValueError('档案格式不受支持')
        code=root/config['code'];account=root/config['account'];data=root/'data'
        if not code.is_dir():raise ValueError('原始备份路径不可读，请重新定位档案')
        # Never write to original ZIP/JSONL. Derived indexes live in the selected work directory.
        index=BackupIndex(code,data);archive=ArchiveCatalog(index,account)
        self.index=index;self.archive=archive;self.staging=Staging(index);self.root=root;self.jobs={}
        journal=data/'native-import-jobs.json'
        if journal.is_file():
            previous=json.loads(journal.read_text())
            for key,job in previous.items():
                if job['status']=='running':job['status']='interrupted'
                self.jobs[key]=job
        source_changes=False
        task=root/'backup-task.json'
        if task.is_file():
            previous=json.loads(task.read_text())
            try:
                previous_files={e['source']:(e['bytes'],e.get('source_mtime_ns')) for e in previous['entries'] if e['status']=='done'}
                from native_backup import source_files
                current={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for source in previous.get('sources',[]) for p,_ in source_files(source)}
                source_changes=current!=previous_files
            except (OSError,ValueError):pass
        return {'root':str(root),'status':config.get('status'),'source_changes':source_changes,'jobs':[{'id':k,**v} for k,v in self.jobs.items() if v.get('kind')=='import']}
    def migrate(self,path):
        if not self.archive:raise ValueError('请先打开档案')
        source=Path(path).resolve();copied=[]
        for name in ('reviews.json','imports.json'):
            origin=source/name;target=self.archive.data/name
            if origin.is_file():
                incoming=json.loads(origin.read_text());existing=json.loads(target.read_text()) if target.exists() else {}
                if not isinstance(incoming,dict):raise ValueError('整理状态格式无效')
                atomic_json(target,{**incoming,**existing});copied.append(name)
        self.archive.refresh()
        return {'copied':copied}
    def import_batch(self,ids,destination='codex',branches=None):
        from target_imports import DESTINATIONS,import_to_target
        if not self.archive:raise ValueError('请先打开档案')
        if destination not in DESTINATIONS:raise ValueError('未知的导入目的地')
        if not isinstance(ids,list) or not ids or not all(isinstance(s,str) for s in ids):raise ValueError('请选择会话')
        branches={} if branches is None else branches
        if not isinstance(branches,dict) or any(s not in ids or not isinstance(b,str) for s,b in branches.items()):raise ValueError('分支选择无效')
        for sid in ids:self.archive.get(sid)
        with self.lock:
            if any(j['status']=='running' for j in self.jobs.values()) or any(s.view()['status']=='running' for s in self.snapshots.values()):raise ValueError('请等待当前任务结束')
            key=uuid.uuid4().hex
            self.jobs[key]={'kind':'import','status':'running','destination':destination,'branches':dict(branches),'ids':list(dict.fromkeys(ids)),'total':len(set(ids)),'completed':0,'results':[],'errors':[],'entries':{}}
        journal=self.archive.data/'native-import-jobs.json'
        def persist():atomic_json(journal,{k:v for k,v in self.jobs.items() if v.get('kind')=='import'})
        persist()
        def run():
            from codex_bridge import make_context_thread,make_account_context_thread
            try:
                for sid in self.jobs[key]['ids']:
                    if self.cancel_imports.is_set():break
                    try:
                        self.archive.reconcile();row=self.archive.get(sid)
                        if not row['valid_hash']:raise ValueError('源文件校验失败')
                        if row['source']=='account' and not row['content_available']:raise ValueError('没有可恢复正文')
                        if destination=='codex':
                            if row['status'] in ('present','archived'):result={'status':'skipped','thread_id':row.get('destination_thread_id')}
                            else:result=make_context_thread(self.index,row['code_id']) if row['source']=='code' else make_account_context_thread(self.archive,sid)
                        else:
                            def progress(record):
                                self.jobs[key]['entries'][sid]=record;persist()
                            result=import_to_target(self.archive,sid,destination,branches.get(sid,''),self.cancel_imports,progress)
                        self.jobs[key]['results'].append({'id':sid,'title':row['title'],'destination':destination,**result})
                    except Exception as error:self.jobs[key]['errors'].append({'id':sid,'error':str(error)})
                    self.jobs[key]['completed']+=1;persist()
                self.archive.reconcile()
            finally:
                status='interrupted' if self.cancel_imports.is_set() else 'completed'
                # Publish completion only after the terminal journal is durable.
                final={**self.jobs[key],'status':status}
                atomic_json(journal,{k:final if k==key else v for k,v in self.jobs.items() if v.get('kind')=='import'})
                self.jobs[key]['status']=status
        threading.Thread(target=run,daemon=True).start()
        return {'job_id':key}

service=NativeService()
Base=make_handler(service)
class Handler(Base):
    def do_GET(self):
        path,params=self._query()
        if path.startswith('/native/'):
            if not self._authenticated():return self._error('未授权',403)
            try:
                if path=='/native/backup':self._json(service.snapshots[self._param(params,'id')].view())
                elif path=='/native/download':self._json(service.jobs[self._param(params,'id')])
                elif path=='/native/library':
                    from account_recovery import library_page
                    self._json(library_page(service.archive,{k:self._param(params,k) for k in params}))
                elif path=='/native/artifact-preview':
                    from account_recovery import artifacts
                    self._json(artifacts(service.archive.account_dir,self._param(params,'id'),self._param(params,'version'),html_preview=True))
                elif path=='/native/account-reading':
                    from account_recovery import account_page
                    self._json(account_page(service.archive,self._param(params,'id'),int(self._param(params,'offset','0')),self._param(params,'branch')))
                elif path=='/native/artifacts':
                    from account_recovery import artifacts
                    self._json(artifacts(service.archive.account_dir,self._param(params,'id'),self._param(params,'version'),int(self._param(params,'offset','0'))))
                elif path=='/native/session':self._json(service.archive.get(self._param(params,'id')))
                elif path=='/native/reading-navigation':
                    identifier=self._param(params,'id')
                    if service.archive.get(identifier)['source']=='account':
                        from account_recovery import account_page
                        self._json(account_page(service.archive,identifier,branch=self._param(params,'branch'),index_only=True))
                    else:self._json(service.archive.reading_navigation(identifier))
                elif path=='/native/messages':self._json(service.archive.reading_messages(self._param(params,'id'),int(self._param(params,'offset','0'))))
                else:self._error('未知接口',404)
            except Exception as error:self._error(str(error))
        elif path.startswith('/api/') and not service.archive:self._error('请先打开档案')
        else:super().do_GET()
    def do_POST(self):
        path,_=self._query()
        if not path.startswith('/native/'):
            if not service.archive:return self._error('请先打开档案')
            return super().do_POST()
        if not self._authenticated() or not self._csrf():return self._error('未授权',403)
        try:
            body=self._body()
            if path=='/native/detect':value=service.detect(body.get('codex',''),body.get('claude',''))
            elif path=='/native/library/update':
                from account_recovery import update_library
                value=update_library(service.archive,body['id'],body.get('title'),body.get('archived'))
            elif path=='/native/source':value=describe(body['path'])
            elif path=='/native/discover':value=discover_sources(body['path'])
            elif path=='/native/download/start':
                from native_download import prepare, run
                if any(j.get('kind')=='download' and j.get('status')=='running' for j in service.jobs.values()):raise ValueError('已有下载任务正在运行')
                root,items=prepare(body['manifest'],body['destination'],body.get('resume',False))
                key=uuid.uuid4().hex;state={'kind':'download','status':'running','root':str(root)};service.jobs[key]=state
                def download_task():
                    try:run(root,items,state)
                    except Exception:state.update(status='failed',message='下载任务中断，请检查磁盘空间与写入权限，再恢复下载。')
                threading.Thread(target=download_task,daemon=True).start();value={'id':key,'root':str(root)}
            elif path=='/native/destination/default':value=destination_info(default_destination(),body.get('sources',[]),allow_missing=True)
            elif path=='/native/destination':value=destination_info(body['path'],body['sources'])
            elif path=='/native/backup/start':
                if any(s.view()['status']=='running' for s in service.snapshots.values()):raise ValueError('已有备份任务正在运行')
                snapshot=Snapshot(body.get('sources'),body.get('destination'),body.get('resume'));key=uuid.uuid4().hex;service.snapshots[key]=snapshot
                threading.Thread(target=snapshot.run,daemon=True).start();value={'id':key,'root':str(snapshot.root)}
            elif path=='/native/backup/cancel':service.snapshots[body['id']].cancel.set();value={'ok':True}
            elif path=='/native/open':value=service.open_archive(body)
            elif path=='/native/migrate':value=service.migrate(body['path'])
            elif path=='/native/import':
                branches=body.get('branches',{})
                if 'branch' in body:
                    if not isinstance(body['ids'],list) or len(body['ids'])!=1:raise ValueError('单条分支参数只支持一条聊天')
                    branches={body['ids'][0]:body['branch']}
                value=service.import_batch(body['ids'],body.get('destination','codex'),branches)
            elif path=='/native/export':
                if not service.archive:raise ValueError('请先打开档案')
                key=uuid.uuid4().hex;ids=body.get('ids');mode=body.get('mode','readable');destination=Path(body['destination']).resolve()
                if not destination.is_dir() or not os.access(destination,os.W_OK):raise ValueError('导出位置不可写')
                service.jobs[key]={'status':'running','total':len(ids) if ids is not None else len(service.archive.sessions),'completed':0,'results':[],'errors':[]}
                def export():
                    try:
                        result=export_markdown(service.archive,ids,mode,destination);service.jobs[key]['results'].append(result);service.jobs[key]['completed']=result['count']
                    except Exception as error:service.jobs[key]['errors'].append({'error':str(error)})
                    finally:service.jobs[key]['status']='completed'
                threading.Thread(target=export,daemon=True).start();value={'job_id':key}
            else:raise ValueError('未知接口')
            self._json(value)
        except Exception as error:self._error(str(error))

if __name__=='__main__':
    os.umask(0o077)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    print(json.dumps({'port':server.server_port,'token':service.token}),flush=True)
    def parent_watch():
        sys.stdin.buffer.read()
        service.cancel_imports.set()
        for snapshot in service.snapshots.values():snapshot.cancel.set()
        server.shutdown()
    threading.Thread(target=parent_watch,daemon=True).start()
    server.serve_forever()
