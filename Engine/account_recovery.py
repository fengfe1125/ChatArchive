"""Read exported account structure and artifact versions without executing content."""
from __future__ import annotations
import json
import zipfile
from pathlib import Path
from html.parser import HTMLParser


def saved_block(block):
    kind = block.get('type', 'unknown')
    if kind == 'thinking':
        text = block.get('thinking') or block.get('summaries') or ''
        title = '思考过程'
    elif kind == 'tool_use':
        text = block.get('input') or block.get('display_content') or block.get('message') or ''
        title = '使用工具 · ' + str(block.get('name') or '工具')
    elif kind == 'tool_result':
        text = block.get('content') or block.get('structured_content') or block.get('display_content') or ''
        title = '工具结果 · ' + str(block.get('name') or '工具')
    else:
        text = block
        title = '其他记录 · ' + str(kind)
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, indent=2)
    return {'type': kind, 'name': title, 'available': 'true', 'text': text or '导出中仅保留了此记录的元数据。'}


def branch_paths(messages):
    """Return every leaf ancestry. Never invent an active branch absent from export."""
    nodes = {str(m['uuid']): m for m in messages if m.get('uuid')}
    parents = {str(m.get('parent_message_uuid')) for m in messages}
    leaves = [key for key in nodes if key not in parents]
    if not nodes or len(nodes) != len(messages):
        return []
    paths = []
    for leaf in leaves:
        chain, seen, current = [], set(), leaf
        while current in nodes and current not in seen:
            seen.add(current); chain.append(current)
            current = str(nodes[current].get('parent_message_uuid'))
        paths.append({'id': leaf, 'nodes': list(reversed(chain)), 'timestamp': nodes[leaf].get('created_at') or ''})
    return sorted(paths, key=lambda p: p['timestamp'], reverse=True)


def account_page(catalog, session_id, offset=0, branch='', index_only=False):
    from archive_core import _account_message, _reading_parts
    row = catalog.get(session_id)
    if row['source'] != 'account' or not row['valid_hash']:
        raise ValueError('不是可读取的账号聊天')
    raw = Path(row['raw_cache_file'])
    from import_core import sha256
    if sha256(raw) != row['raw_cache_sha256']:
        raise ValueError('账号原始记录缓存校验失败')
    original = json.loads(raw.read_text())
    messages = original.get('chat_messages') or original.get('messages') or []
    paths = branch_paths(messages)
    selected = next((p for p in paths if p['id'] == branch), None) if branch else (paths[0] if paths else None)
    if branch == 'all': selected = None
    elif branch and selected is None: raise ValueError('聊天分支不存在')
    if selected:
        nodes = {m['uuid']:m for m in messages}
        messages = [nodes[key] for key in selected['nodes']]
    original_messages = original.get('chat_messages') or original.get('messages') or []
    siblings = {}
    for message in original_messages:
        if message.get('uuid') and message.get('parent_message_uuid'):
            siblings.setdefault(message['parent_message_uuid'], []).append(message)
    def metadata(m, ordinal):
        alternatives=siblings.get(m.get('parent_message_uuid'), [])
        versions=[]
        for alternate in alternatives:
            target=next((p for p in paths if alternate['uuid'] in p['nodes']),None)
            if target:versions.append({'id':target['id'], 'title':alternate.get('created_at',''), 'message_id':alternate['uuid']})
        return {'message_id':str(m.get('uuid') or f'record-{ordinal}'),
                'versions':versions if len(versions)>1 else [],
                'version_index':next((i for i,v in enumerate(versions) if v['message_id']==m.get('uuid')),0)}
    # Preserve block order in the native reader, including text between tools.
    def events():
        for ordinal,m in enumerate(messages):
            meta=metadata(m,ordinal)
            content = m.get('content')
            if isinstance(content, list) and content:
                for block in content:
                    # System-injected context remains in raw records, not user chat bubbles.
                    if isinstance(block, dict) and block.get('type') == 'injected_prompt_block':
                        continue
                    event = _account_message({**m, 'content':[block], 'text':'', 'attachments':[], 'files':[]})
                    if event: yield {**event, **meta}
                extras = _account_message({**m, 'content':[], 'text':''})
                if extras: yield {**extras, **meta}
            else:
                event = _account_message(m)
                if event: yield {**event, **meta}
    from itertools import islice
    parts = ({**part, 'message_id':event['message_id'], 'versions':event['versions'], 'version_index':event['version_index']} for event in events() for part in _reading_parts(event) if part['text'] or part.get('media'))
    if index_only:
        entries=[]; seen={}; has_text=set()
        for position,part in enumerate(parts):
            key=part['message_id']
            if key in seen:
                if part['text'] and key not in has_text:
                    entries[seen[key]]['preview']=' '.join(part['text'].split())[:100];has_text.add(key)
                continue
            seen[key]=len(entries)
            if part['text']:has_text.add(key)
            preview=part['text'] or next((m.get('name','附件') for m in part.get('media',[])), '消息')
            entries.append({'id':key,'offset':position,'role':part['role'],'preview':' '.join(preview.split())[:100]})
        return {'items':entries}
    if offset < 0:
        from collections import deque
        tail=deque(maxlen=8); total=0
        for part in parts:tail.append(part);total+=1
        offset=max(0,total-len(tail));page=list(tail)
    else:
        page = list(islice(parts, offset, offset+9))
    artifact_items=artifacts(catalog.account_dir)['items'] if hasattr(catalog,'account_dir') else []
    serialized=json.dumps(original,ensure_ascii=False)
    related=[a for a in artifact_items if a['id'] in serialized]
    return {'artifacts':related,'start_offset':offset,'previous_offset':max(0,offset-8) if offset>0 else None,'items':page[:8], 'next_offset':offset+8 if len(page)>8 else None,
            'branch': selected['id'] if selected else 'all',
            'branches':[{'id':p['id'], 'title':f"分支 {i+1} · {p['timestamp'][:16].replace('T',' ')}"} for i,p in enumerate(paths)]}


class ReadableHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','head'): self.hidden+=1
        if tag in ('p','div','h1','h2','h3','li','tr','br','pre'):self.parts.append('\n')
        if tag in ('td','th'):self.parts.append(' | ')
    def handle_endtag(self, tag):
        if tag in ('script','style','head'):self.hidden=max(0,self.hidden-1)
        if tag in ('p','div','h1','h2','h3','li','tr','pre'):self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden:self.parts.append(data)


def artifacts(account_dir, identifier='', version='', offset=0, html_preview=False):
    path = account_dir / 'frames-000.zip'
    if not path.exists():return {'items':[], 'available':False}
    with zipfile.ZipFile(path) as archive:
        metadata=[]
        for name in archive.namelist():
            if name.startswith('artifacts/') and name.endswith('/artifact.json'):
                item=json.loads(archive.read(name)); item['_directory']=name.rsplit('/',1)[0];metadata.append(item)
        if not identifier:
            return {'available':True,'items':[{'id':str(m['id']), 'title':next((v.get('title') for v in m.get('versions',[]) if v['id']==m.get('active_version')),None) or '未命名作品', 'versions':[{'id':v['id'],'title':v.get('title') or v['id']} for v in m.get('versions',[])]} for m in metadata]}
        item=next((m for m in metadata if str(m['id'])==identifier),None)
        if item is None:raise ValueError('作品不存在')
        version=version or item.get('active_version')
        if version not in {v['id'] for v in item.get('versions',[])}:raise ValueError('作品版本不存在')
        html=archive.read(item['_directory']+'/versions/'+version+'.html').decode('utf-8',errors='replace')
        if html_preview:return {'html':html,'version':version,'title':next(v.get('title','作品') for v in item['versions'] if v['id']==version)}
        parser=ReadableHTML();parser.feed(html)
        import re
        text=re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',''.join(parser.parts)).strip()
        offset=max(0,offset);end=offset+12000
        return {'content':text[offset:end], 'next_offset':end if end<len(text) else None, 'version':version}


def conversation_title(item, messages):
    """Use recorded titles first; make missing-title records distinguishable, never invented."""
    title = str(item.get('name') or item.get('title') or '').strip()
    if title:return title[:180]
    for role in ('user','assistant'):
        for message in messages:
            if message['role']==role and message['text'].strip():
                return ' '.join(message['text'].split())[:70]
    stamp=str(item.get('created_at') or item.get('updated_at') or '')[:16].replace('T',' ')
    identity=str(item.get('uuid') or item.get('id') or '')[:6]
    # Attachment filenames are evidence, not a reconstructed conversation title.
    names=[]
    for message in messages:
        for media in message.get('media',[]):
            name=media.get('name','')
            if name not in ('','附件') and media.get('type') not in ('thinking','tool_use','tool_result','injected_prompt_block') and name not in names:
                names.append(name)
    if names:return ('附件：'+names[0]+' · '+(stamp[:10] or identity))[:180]
    return ('对话 · '+(stamp or '日期未知')+' · '+identity).strip(' ·')


def library_state(catalog):
    path=catalog.data/'library-state.json'
    return json.loads(path.read_text()) if path.exists() else {}


def apply_library_state(catalog):
    for key,state in library_state(catalog).items():
        if key in catalog.sessions:
            row=catalog.sessions[key]
            if state.get('title'):row['title']=state['title']
            row['local_archived']=bool(state.get('archived'))


def update_library(catalog, identifier, title=None, archived=None):
    from import_core import atomic_json
    row=catalog.get(identifier); state=library_state(catalog);record=state.setdefault(identifier,{})
    if title is not None:
        title=str(title).strip()
        if not title or len(title)>180:raise ValueError('标题需为 1 至 180 个字符')
        record['title']=title
    if archived is not None:record['archived']=bool(archived)
    atomic_json(catalog.data/'library-state.json',state);apply_library_state(catalog)
    return row


def library_page(catalog, params):
    rows=catalog.list(query=params.get('query',''),source=params.get('source',''),project=params.get('project',''),
                      status=params.get('status',''),review=params.get('review',''),code=params.get('code',''),
                      date_from=params.get('from',''),date_to=params.get('to',''),size=max(1,len(catalog.sessions)))['items']
    scope=params.get('scope','chats')
    def missing_body(row):
        return row.get('source')=='account' and row.get('content_available') is False
    if scope=='missing':rows=[r for r in rows if missing_body(r)]
    else:rows=[r for r in rows if not missing_body(r) and bool(r.get('local_archived'))==(scope=='archived')]
    if scope=='starred':rows=[r for r in rows if r.get('review')=='useful']
    page=max(1,int(params.get('page','1')));size=40
    return {'items':rows[(page-1)*size:page*size],'total':len(rows),'page':page,'size':size}
