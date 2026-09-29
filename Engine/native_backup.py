"""Allowlisted, verified snapshots. Never follows source symlinks or overwrites originals."""
from pathlib import Path
import json, os, shutil, threading, time, uuid, zipfile
from import_core import atomic_json, sha256

ZIP_NAMES = {'conversations-000.zip', 'frames-000.zip', 'memories-000.zip', 'light_metadata-000.zip'}

def source_files(root):
    root = Path(root).expanduser().resolve()
    if root.is_file():
        if root.name not in ZIP_NAMES:
            raise ValueError('请选择 Claude 官方导出 ZIP，文件名需保留原名')
        yield root, 'account/' + root.name
        return
    if not root.is_dir():
        raise ValueError('来源目录不存在')
    for folder in ('projects', 'file-history'):
        base = root / folder
        if base.is_symlink():
            continue
        if base.is_dir():
            for directory, dirs, files in os.walk(base, followlinks=False):
                dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink() and (folder!='projects' or d not in ('.git','worktrees','skills','memory'))]
                for name in sorted(files):
                    path = Path(directory)/name
                    if path.is_symlink() or not path.is_file():
                        continue
                    if folder == 'projects' and not (name.endswith('.jsonl') or name == 'sessions-index.json'):
                        continue
                    yield path, 'code/' + path.relative_to(root).as_posix()
    history = root/'history.jsonl'
    if history.is_file() and not history.is_symlink():
        yield history, 'code/history.jsonl'
    for name in sorted(ZIP_NAMES):
        path = root/name
        if path.is_file() and not path.is_symlink():
            yield path, 'account/'+name

def describe(path):
    items = list(source_files(path))
    return {'path':str(Path(path).expanduser().resolve()),'files':len(items),
            'sessions':sum(rel.startswith('code/projects/') and rel.endswith('.jsonl') and not p.name.startswith('agent-') and '/subagents/' not in rel for p,rel in items),
            'bytes':sum(p.stat().st_size for p,_ in items),
            'modified':max((p.stat().st_mtime for p,_ in items),default=0),
            'kind':('mixed' if any(r.startswith('code/') for _,r in items) else 'account') if any(r.startswith('account/') for _,r in items) else 'code',
            'zip_count':sum(r.startswith('account/') for _,r in items)}

def discover_sources(path, max_depth=6, max_dirs=3000):
    """Bounded read-only discovery. Never descend into symlinks or project repositories."""
    root = Path(path).expanduser()
    if root.is_symlink(): raise ValueError('请选择实际文件夹，不支持符号链接')
    root = root.resolve()
    if not root.exists(): raise ValueError('来源不存在')
    found, warnings = [], []
    def inspect(folder):
        item = describe(folder)
        if not item['files']: return False
        # A projects directory alone is insufficient; require a Claude message record.
        if item['kind'] in ('code', 'mixed'):
            valid = False
            for file, rel in source_files(folder):
                if not rel.startswith('code/projects/') or not rel.endswith('.jsonl'): continue
                with file.open('rb') as stream:
                    for _ in range(30):
                        line = stream.readline(1024 * 1024)
                        if not line: break
                        try: row = json.loads(line)
                        except (ValueError, UnicodeError): continue
                        if isinstance(row,dict) and row.get('type') in ('user','assistant') and isinstance(row.get('message'),dict):
                            valid = True; break
                if valid: break
            if not valid: return False
        for file, rel in source_files(folder):
            if rel.startswith('account/'):
                with zipfile.ZipFile(file) as archive:
                    if not any(n.endswith(('.json','.jsonl')) for n in archive.namelist()):
                        raise ValueError('ZIP 中没有可识别的 JSON 记录')
        found.append(item)
        return True
    if root.is_file():
        inspect(root)
    else:
        skipped = {'.git','node_modules','dist','.build','.versions','__pycache__','venv','.venv','worktrees','skills'}
        visited = 0
        def onerror(error): warnings.append(str(error))
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            visited += 1
            if visited > max_dirs:
                warnings.append('文件夹较大，已到扫描上限；请选择更具体的子文件夹继续检测。'); break
            current = Path(directory)
            dirs[:] = sorted(d for d in dirs if d not in skipped and not d.endswith('.app') and not (current/d).is_symlink())
            try:
                if ('projects' in dirs or any(n in ZIP_NAMES for n in files)) and inspect(current):
                    dirs[:] = []
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                warnings.append(str(current)+': '+str(error))
                dirs[:] = []
            if len(current.relative_to(root).parts) >= max_depth and dirs:
                warnings.append(str(current)+': 达到扫描深度，请单独选择此目录继续检测。'); dirs[:] = []
    return {'sources':found,'warnings':warnings,
            'message':f'识别到 {len(found)} 个来源；可按类型勾选。' if found else '没有识别到聊天备份。支持含 projects 的 Claude Code 目录和保留官方文件名的账号导出 ZIP。'}

def default_destination():
    return Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex').expanduser().resolve()/'chat-archive'

def destination_info(destination, sources, allow_missing=False):
    target = Path(destination).expanduser().resolve()
    probe=target
    if allow_missing:
        while not probe.exists():probe=probe.parent
    if not probe.is_dir(): raise ValueError('备份位置不存在，请先选择目录')
    if not os.access(probe, os.W_OK): raise ValueError('备份位置不可写')
    for source in sources:
        source = Path(source).expanduser().resolve()
        if target == source or target.is_relative_to(source) or source.is_relative_to(target):
            raise ValueError('备份位置与来源存在包含关系，请选择其他目录')
    size = sum(describe(source)['bytes'] for source in sources)
    free = shutil.disk_usage(probe).free
    if free < size + 64*1024*1024: raise ValueError('可用空间不足，请更换备份位置')
    return {'path':str(target),'free':free,'bytes':size}

class Snapshot:
    def __init__(self, sources=None, destination=None, resume=None):
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        if resume:
            self.root=Path(resume).resolve()
            self.state=json.loads((self.root/'backup-task.json').read_text())
            if self.state.get('format')!=1: raise ValueError('不支持的备份任务格式')
        else:
            if Path(destination).expanduser().resolve()==default_destination():
                destination_info(destination,sources,allow_missing=True)
                Path(destination).mkdir(parents=True,exist_ok=True,mode=0o700)
            destination_info(destination,sources)
            self.root=Path(destination).resolve()/('聊天档案-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
            self.root.mkdir(mode=0o700)
            entries={}
            for source in sources:
                for path,relative in source_files(source):
                    if relative in entries and entries[relative]['source']!=str(path):
                        raise ValueError('来源包含同名记录，请分成不同批次备份：'+relative)
                    entries[relative]={'source':str(path),'path':relative,'status':'pending','bytes':path.stat().st_size}
            if not entries: raise ValueError('来源中没有可备份的聊天或 ZIP')
            self.state={'format':1,'sources':list(sources),'root':str(self.root),'status':'pending','entries':list(entries.values()),'total':len(entries),'completed':0,'copied_bytes':0,'errors':[]}
            self.persist()
    def persist(self): atomic_json(self.root/'backup-task.json',self.state)
    def view(self):
        with self.lock:
            return {k:v for k,v in self.state.items() if k!='entries'}
    def run(self):
        self.state.update(status='running',errors=[],completed=0,copied_bytes=0)
        self.persist()
        try:
            for entry in self.state['entries']:
                if self.cancel.is_set(): break
                relative=Path(entry['path'])
                if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in ('code','account'):
                    raise ValueError('备份任务中存在无效目标路径')
                target=self.root/relative
                if target.is_symlink() or not target.resolve().is_relative_to(self.root): raise ValueError('目标路径已变化')
                if entry['status']=='done' and target.is_file() and sha256(target)==entry.get('sha256'):
                    self.state['completed']+=1;self.state['copied_bytes']+=target.stat().st_size
                    continue
                try:
                    if target.exists(): raise ValueError('已有目标文件未通过校验，保留原文件，请创建新批次')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    source=Path(entry['source']);temp=target.with_name(target.name+'.copying')
                    if temp.is_symlink(): raise ValueError('临时文件路径冲突')
                    for attempt in range(3):
                        self.state['current']=relative.as_posix();self.state['phase']='复制';self.state['current_bytes']=0
                        before=source.stat()
                        if source.is_symlink(): raise ValueError('来源变为符号链接')
                        with source.open('rb') as src,temp.open('wb') as dst:
                            while chunk:=src.read(1024*1024):
                                if self.cancel.is_set(): break
                                dst.write(chunk);self.state['current_bytes']+=len(chunk)
                            dst.flush();os.fsync(dst.fileno())
                        if self.cancel.is_set(): break
                        self.state['phase']='校验';digest=sha256(temp);after=source.stat()
                        if (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns) and digest==sha256(source):
                            if target.suffix=='.zip':
                                with zipfile.ZipFile(temp) as archive:
                                    if archive.testzip():raise ValueError('ZIP 完整性校验失败')
                            os.replace(temp,target);target.chmod(0o600)
                            entry.update(status='done',sha256=digest,bytes=target.stat().st_size,source_mtime_ns=after.st_mtime_ns)
                            self.state['completed']+=1;self.state['copied_bytes']+=entry['bytes'];self.state['current_bytes']=0;break
                    else: raise ValueError('来源持续变化，请结束对应会话后重试')
                    if self.cancel.is_set(): break
                except Exception as error:
                    entry['status']='failed';self.state['errors'].append({'path':entry['path'],'error':str(error)})
                self.persist()
            code=self.root/'code';code.mkdir(exist_ok=True)
            atomic_json(code/'manifest.json',{'files':[{'path':e['path'][5:],'sha256':e['sha256']} for e in self.state['entries'] if e['status']=='done' and e['path'].startswith('code/')]})
            (self.root/'account').mkdir(exist_ok=True)
            self.state['status']='cancelled' if self.cancel.is_set() else 'partial' if self.state['errors'] else 'completed'
            atomic_json(self.root/'archive.json',{'format':1,'code':'code','account':'account','data':'data','status':self.state['status']})
        except Exception as error:
            self.state['errors'].append({'error':str(error)});self.state['status']='partial'
        finally:self.persist()
