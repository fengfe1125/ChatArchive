"""Unified, source-backed reading index for Claude Code and account exports."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import zipfile
from typing import Any, Iterator

from account_download import DESTINATION as ACCOUNT_DIR, digest_file
from import_core import BackupIndex, atomic_json, parse_time, sha256


FENCE = re.compile(r"(?:^|\n)(`{3,}|~{3,})([^\n]*)\n(.*?)(?:\n\1(?=\n|$)|$)", re.S)
VISIBLE_KINDS = {"text"}
ACCOUNT_CACHE_VERSION = 6
READING_CHUNK_SIZE = 4000


def _reading_parts(event: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Bound native layout work without truncating the original or exported text."""
    text = event['text']
    split = len(text) > READING_CHUNK_SIZE
    for start in range(0, max(1, len(text)), READING_CHUNK_SIZE):
        yield {'role': event['role'], 'text': text[start:start + READING_CHUNK_SIZE],
               'media': [], 'continuation': start > 0, 'plain': split, 'segmented': split}
    for media in event.get('media', []):
        extracted = media.get('text', '')
        for start in range(0, max(1, len(extracted)), READING_CHUNK_SIZE):
            yield {'role': event['role'], 'text': '', 'continuation': True,
                   'segmented': len(extracted) > READING_CHUNK_SIZE,
                   'media': [{**media, 'text': extracted[start:start + READING_CHUNK_SIZE]}]}


def _text_blocks(content: Any) -> tuple[str, list[dict[str, str]]]:
    """Return human-facing text and unresolved media descriptors."""
    if isinstance(content, str):
        return content, []
    if isinstance(content, dict):
        return _text_blocks(content.get("content", content.get("text", "")))
    if not isinstance(content, list):
        return "", []
    text: list[str] = []
    media: list[dict[str, str]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in VISIBLE_KINDS and isinstance(block.get("text"), str):
            text.append(block["text"])
        elif kind in ("image", "document", "file"):
            source = block.get("source") or {}
            media.append({"type": str(kind), "name": str(block.get("name") or block.get("filename") or "附件"), "available": "false", "detail": str(source.get("type") if isinstance(source, dict) else "")})
    return "\n\n".join(part for part in text if part.strip()), media


def _code_fences(text: str) -> Iterator[tuple[str, str]]:
    for match in FENCE.finditer(text):
        yield match.group(2).strip().split()[0] if match.group(2).strip() else "text", match.group(3)


def _code_events(path: Path, backup: Path, expected: dict[str, str]) -> Iterator[dict[str, Any]]:
    """Stream a Claude Code JSONL. No source file is modified."""
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line_number, line in enumerate(source, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                yield {"kind": "invalid", "line": line_number, "raw": line}
                continue
            kind = record.get("type")
            if kind in ("user", "assistant"):
                message = record.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                body, media = _text_blocks(content)
                yield {"kind": kind, "line": line_number, "timestamp": record.get("timestamp"), "text": body,
                       "media": media, "uuid": record.get("uuid"), "content": content}
                if kind == "assistant" and isinstance(content, list):
                    for block_index, block in enumerate(content):
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        name = block.get("name")
                        data = block.get("input") or {}
                        if name not in ("Write", "Edit", "MultiEdit", "NotebookEdit") or not isinstance(data, dict):
                            continue
                        file_path = data.get("file_path") or data.get("notebook_path") or "未知文件"
                        if name == "Write":
                            code = data.get("content") or ""
                            completeness = "完整写入内容"
                        elif name == "Edit":
                            code = f"--- 原片段\n{data.get('old_string', '')}\n+++ 新片段\n{data.get('new_string', '')}"
                            completeness = "编辑片段，非完整文件"
                        else:
                            code = json.dumps(data, ensure_ascii=False, indent=2)
                            completeness = "工具改动记录，非完整文件"
                        yield {"kind": "code", "line": line_number, "id": f"{line_number}:tool:{block_index}", "title": str(file_path),
                               "language": Path(str(file_path)).suffix.removeprefix(".") or "text", "origin": str(name),
                               "completeness": completeness, "content": str(code), "timestamp": record.get("timestamp"),
                               "before": data.get("old_string") if name == "Edit" else None,
                               "after": data.get("new_string") if name == "Edit" else None}
            elif kind == "attachment" and isinstance(record.get("attachment"), dict):
                attachment = record["attachment"]
                if attachment.get("type") in ("file", "edited_text_file", "compact_file_reference"):
                    yield {"kind": "attachment", "line": line_number, "timestamp": record.get("timestamp"),
                           "name": str(attachment.get("displayPath") or attachment.get("filename") or "附件"),
                           "available": bool(attachment.get("content")), "parent": record.get("parentUuid")}
            elif kind in ("file-history-snapshot", "file-history-delta"):
                snapshot = record.get("snapshot") or {}
                tracked = snapshot.get("trackedFileBackups") if kind == "file-history-snapshot" else {record.get("trackingPath"): record.get("backup")}
                if not isinstance(tracked, dict):
                    continue
                for item_index, (file_path, info) in enumerate(tracked.items()):
                    if not isinstance(info, dict) or not isinstance(info.get("backupFileName"), str):
                        continue
                    relative = f"file-history/{path.stem}/{info['backupFileName']}"
                    actual = backup / relative
                    if not actual.is_file() or expected.get(relative) != sha256(actual):
                        continue
                    yield {"kind": "code", "line": line_number, "id": f"{line_number}:history:{item_index}", "title": str(file_path),
                           "language": Path(str(file_path)).suffix.removeprefix(".") or "text", "origin": "file-history",
                           "completeness": "备份中的文件版本", "content_path": str(actual), "timestamp": record.get("timestamp")}
            else:
                yield {"kind": "other", "line": line_number, "type": str(kind or "unknown"), "timestamp": record.get("timestamp")}


def _visible_code(events: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Merge adjacent text fragments across hidden tool traffic, within a user turn."""
    pending: dict[str, Any] | None = None
    for event in events:
        kind = event["kind"]
        if kind in ("user", "assistant") and (event["text"].strip() or event["media"]):
            if pending and pending["role"] == kind:
                if event["text"].strip():
                    pending["text"] += ("\n\n" if pending["text"] else "") + event["text"]
                pending["media"].extend(event["media"])
                pending["last_line"] = event["line"]
            else:
                if pending:
                    yield pending
                pending = {"role": kind, "text": event["text"], "media": list(event["media"]),
                           "timestamp": event.get("timestamp"), "line": event["line"], "last_line": event["line"]}
        elif kind == "attachment" and pending and event.get("parent"):
            pending["media"].append({"type": "file", "name": event["name"], "available": str(event["available"]).lower()})
    if pending:
        yield pending


def _account_message(message: dict[str, Any]) -> dict[str, Any] | None:
    sender = message.get("sender") or message.get("role") or (message.get("author") or {}).get("role")
    if isinstance(sender, dict):
        sender = sender.get("role") or sender.get("type")
    role = "user" if str(sender).lower() in ("human", "user") else "assistant" if str(sender).lower() in ("assistant", "claude") else None
    if role is None:
        return None
    content = message.get("content", message.get("text", ""))
    if isinstance(content, list):
        parts = []
        media = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and not item.get("hidden_in_chat") and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif item.get("type") in ("image", "file", "document"):
                    media.append({"type": str(item["type"]), "name": str(item.get("file_name") or item.get("filename") or item.get("name") or "附件"), "available": "false"})
        text = "\n\n".join(parts)
    elif isinstance(content, dict):
        text = str(content.get("text") or "")
        media = []
    else:
        text = str(content or "")
        media = []
    if not text.strip() and not content and isinstance(message.get("text"), str):
        text = message["text"]
    if isinstance(content, list):
        from account_recovery import saved_block
        for block in content:
            if isinstance(block, dict) and block.get("type") not in ("text", "image", "file", "document"):
                media.append(saved_block(block))
    for item in [*(message.get("attachments") or []), *(message.get("files") or [])]:
        if isinstance(item, dict):
            extracted = item.get("extracted_content") if isinstance(item.get("extracted_content"), str) else ""
            media.append({"type": str(item.get("file_type") or item.get("type") or "file"),
                          "name": str(item.get("file_name") or item.get("filename") or item.get("name") or "附件"),
                          "available": "true" if extracted else "false", "text": extracted})
    if not text.strip() and not media:
        return None
    return {"role": role, "text": text, "media": media, "timestamp": message.get("created_at") or message.get("timestamp")}


def _conversation_objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _conversation_objects(item)
    elif isinstance(value, dict):
        if isinstance(value.get("chat_messages"), list) or isinstance(value.get("messages"), list):
            yield value
        else:
            for key in ("conversations", "data", "items"):
                if key in value:
                    yield from _conversation_objects(value[key])


class ArchiveCatalog:
    def __init__(self, code: BackupIndex, account_dir: Path = ACCOUNT_DIR):
        self.code = code
        self.account_dir = account_dir
        self.data = code.app_data
        self.sessions: dict[str, dict[str, Any]] = {}
        self.account_status = "missing"
        self.refresh()

    def refresh(self) -> None:
        self.code.refresh()
        self.sessions = {}
        for original in self.code.sessions.values():
            row = asdict(original)
            row.update(id="code:" + original.id, source="code", code_id=original.id, review="", visible_turns=0,
                       code_blocks=0, file_changes=0)
            self.sessions[row["id"]] = row
        self._load_account()
        self._reconcile_account()
        self._build_search()
        self._apply_reviews()
        from account_recovery import apply_library_state
        apply_library_state(self)

    def _load_account(self) -> None:
        archive_path = self.account_dir / "conversations-000.zip"
        if not archive_path.is_file():
            self.account_status = "download_failed" if (self.account_dir / "conversations-000.zip.partial").exists() else "missing"
            return
        try:
            with zipfile.ZipFile(archive_path) as archive:
                if archive.testzip():
                    self.account_status = "invalid"
                    return
                source_sha = digest_file(archive_path)
                cache = self.data / "account-cache" / f"{source_sha}-v{ACCOUNT_CACHE_VERSION}"
                index_path = cache / "index.json"
                if index_path.exists():
                    rows = json.loads(index_path.read_text(encoding="utf-8"))
                else:
                    cache.mkdir(parents=True, exist_ok=True)
                    rows = []
                    for member in archive.infolist():
                        if member.is_dir() or not member.filename.lower().endswith((".json", ".jsonl")) or "__MACOSX" in member.filename:
                            continue
                        try:
                            with archive.open(member) as source:
                                if member.filename.lower().endswith(".jsonl"):
                                    objects = (json.loads(line) for line in source if line.strip())
                                    conversations = (conversation for obj in objects for conversation in _conversation_objects(obj))
                                    rows.extend(self._cache_conversations(conversations, cache, archive_path, member.filename, source_sha))
                                else:
                                    value = json.load(source)
                                    rows.extend(self._cache_conversations(_conversation_objects(value), cache, archive_path, member.filename, source_sha))
                        except (ValueError, UnicodeDecodeError):
                            continue
                    atomic_json(index_path, rows)
            for row in rows:
                # Cache paths are derived, and must follow an archive moved to another Mac.
                cache_id = row["id"].split(":", 1)[1]
                row["cache_file"] = str(cache / (cache_id + ".json"))
                row["raw_cache_file"] = str(cache / (cache_id + ".raw.json"))
                row["source_path"] = str(archive_path) + "!" + row["source_path"].split("!", 1)[-1]
                self.sessions[row["id"]] = row
            self.account_status = "ready" if rows else "unsupported"
        except (OSError, zipfile.BadZipFile, ValueError):
            self.account_status = "invalid"

    def _cache_conversations(self, conversations: Iterator[dict[str, Any]], cache: Path, zip_path: Path, member: str, source_sha: str) -> list[dict[str, Any]]:
        rows = []
        for item in conversations:
            messages = [_account_message(m) for m in (item.get("chat_messages") or item.get("messages") or []) if isinstance(m, dict)]
            messages = [m for m in messages if m]
            identifier = str(item.get("uuid") or item.get("id") or hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
            cache_id = hashlib.sha256((member + "\0" + identifier).encode()).hexdigest()
            digest = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            from account_recovery import conversation_title
            title = conversation_title(item, messages)
            project = item.get("project") or item.get("project_name") or "未分类"
            if isinstance(project, dict):
                project = project.get("name") or project.get("title") or "未分类"
            created = item.get("created_at") or (messages[0].get("timestamp") if messages else None)
            updated = item.get("updated_at") or (messages[-1].get("timestamp") if messages else None)
            cache_file = cache / (cache_id + ".json")
            raw_file = cache / (cache_id + ".raw.json")
            atomic_json(cache_file, {"messages": messages, "source_member": member, "source_id": identifier})
            atomic_json(raw_file, item)
            rows.append({"id": "account:" + cache_id, "source": "account", "title": title, "project": str(project), "first_at": created,
                         "last_at": updated, "messages": len(item.get("chat_messages") or item.get("messages") or []), "visible_turns": len(messages),
                         "content_available": any(m["text"].strip() or any(a.get("text", "").strip() for a in m["media"]) for m in messages), "bytes": cache_file.stat().st_size,
                         "sha256": digest, "valid_hash": True, "preview": messages[0]["text"][:220] if messages else "正文未包含在官方导出中", "source_path": str(zip_path) + "!" + member,
                         "archive_sha256": source_sha, "cache_file": str(cache_file), "cache_sha256": sha256(cache_file),
                         "raw_cache_file": str(raw_file), "raw_cache_sha256": sha256(raw_file), "code_blocks": 0, "file_changes": 0,
                         "status": "new", "destination_thread_id": None, "import_method": None, "eligibility": "context", "review": ""})
        return rows

    def _build_search(self) -> None:
        database = self.data / "archive-search.sqlite"
        temporary = self.data / "archive-search.new.sqlite"
        temporary.unlink(missing_ok=True)
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("CREATE TABLE message_text (session_id TEXT, body TEXT)")
            connection.execute("CREATE INDEX by_session ON message_text(session_id)")
            connection.execute("CREATE TABLE reading_message (session_id TEXT, position INTEGER, payload TEXT, PRIMARY KEY(session_id, position))")
            for row in self.sessions.values():
                position = 0
                if row["source"] == "code" and row["valid_hash"]:
                    events = _visible_code(_code_events(Path(row["source_path"]), self.code.backup, self.code.expected))
                elif row["source"] == "account":
                    events = self._account_messages(row)
                else:
                    events = []
                for event in events:
                    for part in _reading_parts(event):
                        connection.execute("INSERT INTO reading_message VALUES (?,?,?)",
                                           (row['id'], position, json.dumps(part, ensure_ascii=False)))
                        position += 1
                    if event["text"].strip():
                        connection.execute("INSERT INTO message_text VALUES (?,?)", (row["id"], event["text"]))
                    for media in event.get("media", []):
                        if media.get("text", "").strip():
                            connection.execute("INSERT INTO message_text VALUES (?,?)", (row["id"], media["text"]))
                    row["visible_turns"] += 1 if row["source"] == "code" else 0
                    row["code_blocks"] += sum(1 for _ in _code_fences(event["text"]))
                if row["source"] == "code" and row["valid_hash"]:
                    row["file_changes"] = sum(event["kind"] == "code" and event.get("origin") != "chat" for event in _code_events(Path(row["source_path"]), self.code.backup, self.code.expected))
            connection.commit()
        finally:
            connection.close()
        temporary.replace(database)

    def _apply_reviews(self) -> None:
        path = self.data / "reviews.json"
        reviews = json.loads(path.read_text()) if path.exists() else {}
        for row in self.sessions.values():
            row["review"] = reviews.get(row["id"], "")

    def set_review(self, session_id: str, value: str) -> None:
        if value not in ("", "useful", "later", "ignore"):
            raise ValueError("未知的标记")
        self.get(session_id)
        path = self.data / "reviews.json"
        reviews = json.loads(path.read_text()) if path.exists() else {}
        if value:
            reviews[session_id] = value
        else:
            reviews.pop(session_id, None)
        atomic_json(path, reviews)
        self.sessions[session_id]["review"] = value

    def _reconcile_account(self) -> None:
        records = self.code._local_records()
        flags = self.code._thread_flags()
        for row in self.sessions.values():
            if row["source"] != "account":
                continue
            record = records.get(f"{row['id']}|{row['sha256']}")
            if record and record.get("thread_id"):
                row["destination_thread_id"] = record["thread_id"]
                row["import_method"] = "context"
                row["status"] = "missing" if record["thread_id"] not in flags else "needs_review" if record.get("status") != "completed" else "archived" if flags[record["thread_id"]] else "present"

    def reconcile(self) -> None:
        self.code.reconcile()
        for row in self.sessions.values():
            if row["source"] == "code":
                original = self.code.get(row["code_id"])
                row["status"] = original.status
                row["destination_thread_id"] = original.destination_thread_id
                row["import_method"] = original.import_method
        self._reconcile_account()

    def get(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise ValueError("未知的会话")
        return self.sessions[session_id]

    def _account_messages(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        path = Path(row["cache_file"])
        if not path.is_file() or sha256(path) != row["cache_sha256"]:
            raise ValueError("账号聊天索引缓存校验失败，请重新扫描备份")
        return json.loads(path.read_text(encoding="utf-8"))["messages"]

    def messages(self, session_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        row = self.get(session_id)
        if not row["valid_hash"]:
            raise ValueError("备份哈希校验失败")
        events = _visible_code(_code_events(Path(row["source_path"]), self.code.backup, self.code.expected)) if row["source"] == "code" else self._account_messages(row)
        selected = []
        for number, event in enumerate(events):
            if number >= offset:
                selected.append(event)
            if len(selected) >= limit:
                break
        next_offset = offset + len(selected)
        return {"items": selected, "next_offset": next_offset if next_offset < row["visible_turns"] else None}

    def reading_navigation(self, session_id: str) -> dict[str, Any]:
        row = self.get(session_id)
        if not row['valid_hash']:raise ValueError('备份哈希校验失败')
        with sqlite3.connect(self.data / 'archive-search.sqlite') as connection:
            records=connection.execute("""SELECT position, json_extract(payload, '$.role'),
                substr(json_extract(payload, '$.text'), 1, 100)
                FROM reading_message WHERE session_id=?
                AND coalesce(json_extract(payload, '$.continuation'), 0)=0 ORDER BY position""", (session_id,)).fetchall()
        return {'items':[{'id':str(position),'offset':position,'role':role,'preview':' '.join(text.split()) or '附件消息'} for position,role,text in records]}

    def reading_messages(self, session_id: str, offset: int = 0) -> dict[str, Any]:
        row = self.get(session_id)
        if not row['valid_hash']:
            raise ValueError('备份哈希校验失败')
        offset = max(0, offset)
        connection = sqlite3.connect(self.data / 'archive-search.sqlite')
        try:
            records = connection.execute(
                'SELECT payload FROM reading_message WHERE session_id=? AND position>=? ORDER BY position LIMIT 5',
                (session_id, offset)).fetchall()
        finally:
            connection.close()
        return {'items': [json.loads(record[0]) for record in records[:4]],
                'next_offset': offset + 4 if len(records) > 4 else None}

    def code_items(self, session_id: str) -> list[dict[str, Any]]:
        row = self.get(session_id)
        items = []
        for index, event in enumerate(self.messages_all(session_id)):
            for number, (language, content) in enumerate(_code_fences(event["text"])):
                items.append({"id": f"chat:{index}:{number}", "title": f"聊天代码块 {index + 1}.{number + 1}", "language": language,
                              "origin": "chat", "completeness": "聊天中的代码块", "bytes": len(content.encode()), "line": event.get("line")})
            for number, media in enumerate(event.get("media", [])):
                suffix = Path(media.get("name", "")).suffix.lower()
                if media.get("text") and suffix in (".py", ".js", ".ts", ".tsx", ".jsx", ".swift", ".html", ".css", ".json", ".sh", ".md", ".sql"):
                    items.append({"id": f"attachment:{index}:{number}", "title": media["name"], "language": suffix.removeprefix("."),
                                  "origin": "attachment", "completeness": "附件提取文本", "bytes": len(media["text"].encode()), "line": event.get("line")})
        if row["source"] == "code":
            seen_history = set()
            for event in _code_events(Path(row["source_path"]), self.code.backup, self.code.expected):
                if event["kind"] == "code":
                    if event.get("origin") == "file-history":
                        identity = (event["title"], event["content_path"])
                        if identity in seen_history:
                            continue
                        seen_history.add(identity)
                    items.append({key: event.get(key) for key in ("id", "title", "language", "origin", "completeness", "line")} | {"bytes": Path(event["content_path"]).stat().st_size if "content_path" in event else len(event["content"].encode())})
        return items

    def code_content(self, session_id: str, item_id: str) -> dict[str, Any]:
        row = self.get(session_id)
        if item_id.startswith("chat:"):
            _, index, number = item_id.split(":")
            event = next((event for i, event in enumerate(self.messages_all(session_id)) if i == int(index)), None)
            if event is None:
                raise ValueError("代码块不存在")
            fences = list(_code_fences(event["text"]))
            if int(number) >= len(fences):
                raise ValueError("代码块不存在")
            return {"content": fences[int(number)][1], "language": fences[int(number)][0]}
        if item_id.startswith("attachment:"):
            _, index, number = item_id.split(":")
            event = next((event for i, event in enumerate(self.messages_all(session_id)) if i == int(index)), None)
            if event is None or int(number) >= len(event.get("media", [])) or not event["media"][int(number)].get("text"):
                raise ValueError("附件内容不存在")
            media = event["media"][int(number)]
            return {"content": media["text"], "language": Path(media["name"]).suffix.removeprefix("."), "completeness": "附件提取文本"}
        if row["source"] == "code":
            for event in _code_events(Path(row["source_path"]), self.code.backup, self.code.expected):
                if event["kind"] == "code" and event["id"] == item_id:
                    content = Path(event["content_path"]).read_text(encoding="utf-8", errors="replace") if "content_path" in event else event["content"]
                    return {"content": content, "language": event["language"], "completeness": event["completeness"],
                            "origin": event["origin"], "source_line": event["line"],
                            "presentation": "diff" if isinstance(event.get("before"), str) and isinstance(event.get("after"), str) else "text",
                            "before": event.get("before"), "after": event.get("after")}
        raise ValueError("代码项不存在")

    def messages_all(self, session_id: str) -> Iterator[dict[str, Any]]:
        row = self.get(session_id)
        return _visible_code(_code_events(Path(row["source_path"]), self.code.backup, self.code.expected)) if row["source"] == "code" else iter(self._account_messages(row))

    def _raw_records(self, session_id: str) -> Iterator[tuple[int, Any]]:
        row = self.get(session_id)
        if not row["valid_hash"]:
            raise ValueError("备份哈希校验失败")
        if row["source"] == "account":
            path = Path(row["raw_cache_file"])
            if sha256(path) != row["raw_cache_sha256"]:
                raise ValueError("账号原始记录缓存校验失败")
            original = json.loads(path.read_text(encoding="utf-8"))
            yield 1, {k: v for k, v in original.items() if k not in ("chat_messages", "messages")}
            for number, message in enumerate(original.get("chat_messages") or original.get("messages") or [], 2):
                yield number, message
        else:
            with Path(row["source_path"]).open("r", encoding="utf-8", errors="replace") as source:
                for number, line in enumerate(source, 1):
                    try:
                        yield number, json.loads(line)
                    except json.JSONDecodeError:
                        yield number, {"type": "invalid", "raw": line}

    def raw(self, session_id: str, offset: int = 0, limit: int = 30) -> dict[str, Any]:
        items = []
        has_more = False
        for number, record in self._raw_records(session_id):
            if number <= offset:
                continue
            if len(items) == limit:
                has_more = True
                break
            kind = (record.get("type") or record.get("sender") or record.get("role") or "metadata") if isinstance(record, dict) else "record"
            preview = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            items.append({"line": number, "type": kind, "timestamp": record.get("timestamp") or record.get("created_at") if isinstance(record, dict) else None,
                          "summary": preview[:180]})
        return {"items": items, "next_offset": offset + len(items) if has_more else None}

    def raw_content(self, session_id: str, line: int, offset: int = 0, limit: int = 32000) -> dict[str, Any]:
        if line < 1 or offset < 0:
            raise ValueError("原始记录位置无效")
        for number, record in self._raw_records(session_id):
            if number == line:
                text = json.dumps(record, ensure_ascii=False, indent=2)
                end = min(offset + limit, len(text))
                return {"content": text[offset:end], "next_offset": end if end < len(text) else None, "total_chars": len(text), "line": line}
        raise ValueError("原始记录不存在")

    def list(self, query: str = "", project: str = "", source: str = "", status: str = "", code: str = "", review: str = "", date_from: str = "", date_to: str = "", page: int = 1, size: int = 20) -> dict[str, Any]:
        rows = list(self.sessions.values())
        if query:
            q = query.casefold()
            connection = sqlite3.connect(self.data / "archive-search.sqlite")
            try:
                hits = {r[0] for r in connection.execute("SELECT DISTINCT session_id FROM message_text WHERE body LIKE ?", ("%" + query + "%",))}
            finally:
                connection.close()
            rows = [r for r in rows if r["id"] in hits or q in (r["title"] + " " + r["project"]).casefold()]
        if source:
            rows = [r for r in rows if r["source"] == source]
        if project:
            rows = [r for r in rows if r["project"] == project]
        if status:
            rows = [r for r in rows if r["status"] == status or r["eligibility"] == status]
        if code == "blocks":
            rows = [r for r in rows if r["code_blocks"]]
        elif code == "files":
            rows = [r for r in rows if r["file_changes"]]
        if review:
            rows = [r for r in rows if r["review"] == review]
        if date_from:
            rows = [r for r in rows if r.get("last_at") and str(r["last_at"])[:10] >= date_from]
        if date_to:
            rows = [r for r in rows if r.get("last_at") and str(r["last_at"])[:10] <= date_to]
        rows.sort(key=lambda r: str(r.get("last_at") or ""), reverse=True)
        start = max(0, page - 1) * size
        return {"total": len(rows), "page": page, "size": size, "items": rows[start:start + size]}
