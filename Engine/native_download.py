"""Download export batches without exposing one-use URLs or extracting archive paths."""
import json, os, shutil, time, uuid, zipfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from import_core import atomic_json, sha256
from native_backup import ZIP_NAMES

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host=urlsplit(newurl).hostname or ''
        if urlsplit(newurl).scheme!='https' or not (host=='claude.ai' or host.endswith('.amazonaws.com')):
            raise ValueError('unsupported redirect')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def read_manifest(path):
    data=json.loads(Path(path).read_text())
    items=data.get('data_files') if isinstance(data,dict) else None
    if not isinstance(items,list) or not items:raise ValueError('不是有效的 Claude 官方导出清单')
    seen=set()
    for item in items:
        if not isinstance(item,dict):raise ValueError('导出清单格式无效')
        name=item.get('filename');url=item.get('export_url','');parsed=urlsplit(url)
        if name not in ZIP_NAMES or name in seen:raise ValueError('清单包含不支持或重复的 ZIP 文件名')
        if parsed.scheme!='https' or parsed.hostname!='claude.ai' or parsed.username or parsed.password:raise ValueError('清单必须使用 Claude 官方 HTTPS 下载链接')
        seen.add(name)
    return items

def prepare(manifest, destination, resume=False):
    items=read_manifest(manifest)
    parent=Path(destination).resolve()
    if not parent.is_dir():raise ValueError('请选择下载保存目录')
    if resume:
        root=parent
        if not (root/'download-state.json').is_file():raise ValueError('该目录不是下载任务')
    else:
        root=parent/('Claude账号导出-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);root.mkdir(mode=0o700)
        shutil.copyfile(manifest,root/'manifest.json');(root/'manifest.json').chmod(0o600)
    return root,items

def run(root, items, state, opener=None):
    opener=opener or build_opener(SafeRedirect()).open
    journal=root/'download-state.json'
    state.update(status='running',total=len(items),completed=0,files=[],root=str(root),message='正在下载')
    def save():atomic_json(journal,state)
    save()
    for item in items:
        name=item['filename'];target=root/name;partial=root/(name+'.partial')
        row={'filename':name,'status':'downloading','bytes':0};state['files'].append(row);state['message']='下载 '+name;save()
        try:
            if target.is_symlink() or partial.is_symlink():raise ValueError('symlink')
            if not target.exists():
                if partial.exists():
                    # Keep partial evidence; retries never overwrite a previous attempt.
                    partial.rename(root/(name+'.partial-'+uuid.uuid4().hex[:8]))
                request=Request(item['export_url'],headers={'User-Agent':'ClaudeArchive/1.0'})
                with opener(request,timeout=30) as response:
                    if 'text/html' in response.headers.get('Content-Type','').lower():raise ValueError('html')
                    expected=response.headers.get('Content-Length');row['expected']=int(expected) if expected else None
                    with partial.open('xb') as output:
                        while True:
                            chunk=response.read(1024*1024)
                            if not chunk:break
                            output.write(chunk);row['bytes']+=len(chunk);save()
                        output.flush();os.fsync(output.fileno())
                    if expected and row['bytes']!=int(expected):raise ValueError('incomplete')
                candidate=partial
            else:candidate=target
            state['message']='校验 '+name;save()
            with zipfile.ZipFile(candidate) as archive:
                if archive.testzip() is not None:raise ValueError('crc')
            row.update(sha256=sha256(candidate),bytes=candidate.stat().st_size,status='verified')
            if candidate==partial:partial.rename(target)
            state['completed']+=1
        except Exception:
            row.update(status='failed',error='下载或 ZIP 校验失败。链接可能已过期、需要网页登录，或网络中断。可重新获取官方清单，或在浏览器下载 ZIP 后选择其文件夹。')
        save()
    state['status']='completed' if state['completed']==state['total'] else 'partial'
    state['message']=f"已核验 {state['completed']} / {state['total']} 个 ZIP。"+('继续选择备份位置后将自动解压读取聊天。' if state['status']=='completed' else '尚未全部完成。链接可能过期、需要网页登录，或网络中断。可恢复下载、使用新清单，或在浏览器下载后添加本地 ZIP。')
    save()
