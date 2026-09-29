"""Read Claude Code backups and prepare safe, reversible Codex imports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable


BACKUP = Path.home() / "Library/Application Support/ChatArchive/unconfigured-source"
APP_DATA = Path.home() / "Library/Application Support/ChatArchive/unconfigured-data"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(filter(None, (block_text(item) for item in content)))
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if isinstance(content.get("content"), (str, list)):
            return block_text(content["content"])
    return ""


def preview_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False) if content is not None else ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text", "")))
        elif kind == "thinking":
            parts.append("［思考记录］\n" + str(block.get("thinking", "")))
        elif kind == "tool_use":
            parts.append("［工具调用：" + str(block.get("name", "未知")) + "］\n" + json.dumps(block.get("input"), ensure_ascii=False))
        elif kind == "tool_result":
            parts.append("［工具结果］\n" + (block_text(block.get("content")) or json.dumps(block.get("content"), ensure_ascii=False)))
        else:
            parts.append("［" + str(kind or "其他内容") + "］\n" + json.dumps(block, ensure_ascii=False))
    return "\n\n".join(parts)


@dataclass
class Session:
    id: str
    source_path: str
    project: str
    title: str
    first_at: str | None
    last_at: str | None
    messages: int
    bytes: int
    sha256: str
    valid_hash: bool
    session_id: str
    preview: str
    agent_paths: list[str] = field(default_factory=list)
    eligibility: str = "unknown"
    status: str = "new"
    destination_thread_id: str | None = None
    import_method: str | None = None


class BackupIndex:
    def __init__(self, backup: Path = BACKUP, app_data: Path = APP_DATA, home: Path | None = None):
        self.backup = backup.resolve()
        self.app_data = app_data.resolve()
        self.app_data.mkdir(parents=True, exist_ok=True)
        self.app_data.chmod(0o700)
        self.home = (home or Path.home()).resolve()
        self.sessions: dict[str, Session] = {}
        self.expected: dict[str, str] = {}
        self.agent_map: dict[str, list[str]] = {}
        self._load_manifest()
        self.refresh()

    def _load_manifest(self) -> None:
        manifest = json.loads((self.backup / "manifest.json").read_text(encoding="utf-8"))
        self.expected = {record["path"]: record["sha256"] for record in manifest["files"]}

    def refresh(self) -> None:
        sessions: dict[str, Session] = {}
        agents: dict[str, list[str]] = {}
        for path in sorted((self.backup / "projects").rglob("*.jsonl")):
            relative = path.relative_to(self.backup).as_posix()
            session_id = path.stem
            if path.name.startswith("agent-"):
                with path.open("r", encoding="utf-8", errors="replace") as source:
                    for line in source:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if record.get("sessionId"):
                            agents.setdefault(str(record["sessionId"]), []).append(relative)
                            break
                continue
            session = self._scan(path, relative, session_id)
            sessions[relative] = session
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        for session in sessions.values():
            session.agent_paths = agents.get(session.session_id, [])
            latest = parse_time(session.last_at)
            session.eligibility = "recent" if latest and latest >= cutoff else "older" if latest else "unknown"
        self.sessions = sessions
        self.agent_map = agents
        self.reconcile()

    def _scan(self, path: Path, relative: str, session_id: str) -> Session:
        first = last = None
        title = ai_title = ""
        cwd = ""
        preview = ""
        count = 0
        with path.open("r", encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = record.get("type")
                if kind == "custom-title" and record.get("customTitle"):
                    title = str(record["customTitle"])
                elif kind == "ai-title" and record.get("aiTitle"):
                    ai_title = str(record["aiTitle"])
                if kind not in ("user", "assistant"):
                    continue
                count += 1
                if record.get("cwd"):
                    cwd = str(record["cwd"])
                if record.get("sessionId"):
                    session_id = str(record["sessionId"])
                timestamp = parse_time(record.get("timestamp"))
                if timestamp:
                    first = min(first, timestamp) if first else timestamp
                    last = max(last, timestamp) if last else timestamp
                if kind == "user" and not preview:
                    body = record.get("message") or {}
                    preview = " ".join(block_text(body.get("content", "")).split())[:220]
        digest = sha256(path)
        return Session(
            id=relative,
            source_path=str(path),
            project=cwd or path.parent.name,
            title=(title or ai_title or preview[:70] or path.stem)[:180],
            first_at=first.isoformat() if first else None,
            last_at=last.isoformat() if last else None,
            messages=count,
            bytes=path.stat().st_size,
            sha256=digest,
            valid_hash=self.expected.get(relative) == digest,
            session_id=session_id,
            preview=preview,
        )

    def get(self, session_id: str) -> Session:
        try:
            return self.sessions[session_id]
        except KeyError as error:
            raise ValueError("未知的会话") from error

    def _thread_flags(self) -> dict[str, bool]:
        database = Path(os.environ.get("CODEX_HOME") or self.home / ".codex").expanduser() / "state_5.sqlite"
        if not database.exists():
            return {}
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            try:
                return {row[0]: bool(row[1]) for row in connection.execute("SELECT id, archived FROM threads")}
            finally:
                connection.close()
        except sqlite3.DatabaseError:
            return {}

    def _official_records(self) -> dict[str, dict[str, Any]]:
        path = Path(os.environ.get("CODEX_HOME") or self.home / ".codex").expanduser() / "external_agent_session_imports.json"
        if not path.exists():
            return {}
        try:
            records = json.loads(path.read_text(encoding="utf-8")).get("records", [])
            return {record["source_path"]: record for record in records if record.get("source_path")}
        except (ValueError, OSError):
            return {}

    def _local_records(self) -> dict[str, dict[str, Any]]:
        path = self.app_data / "imports.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}

    def reconcile(self) -> None:
        flags = self._thread_flags()
        official = self._official_records()
        local = self._local_records()
        for session in self.sessions.values():
            key = f"{session.id}|{session.sha256}"
            record = local.get(key)
            if record and record.get("thread_id"):
                thread_id = record["thread_id"]
                session.destination_thread_id = thread_id
                session.import_method = "context"
                session.status = "missing" if thread_id not in flags else "needs_review" if record.get("status") != "completed" else "archived" if flags[thread_id] else "present"
                continue
            source = str(self.home / ".claude" / session.id)
            record = official.get(source)
            session.destination_thread_id = record.get("imported_thread_id") if record else None
            session.import_method = "official" if record else None
            if not record:
                session.status = "new"
            elif record.get("content_sha256") != session.sha256:
                session.status = "changed"
            elif session.destination_thread_id not in flags:
                session.status = "missing"
            else:
                session.status = "archived" if flags[session.destination_thread_id] else "present"

    def list(self, *, query: str = "", project: str = "", status: str = "", page: int = 1, size: int = 20) -> dict[str, Any]:
        rows = list(self.sessions.values())
        if query:
            q = query.casefold()
            rows = [s for s in rows if q in (s.title + " " + s.preview + " " + s.project).casefold()]
        if project:
            rows = [s for s in rows if s.project == project]
        if status:
            rows = [s for s in rows if s.status == status or s.eligibility == status]
        rows.sort(key=lambda s: s.last_at or "", reverse=True)
        total = len(rows)
        start = max(0, page - 1) * size
        return {"total": total, "page": page, "size": size, "items": [asdict(s) for s in rows[start:start + size]]}

    def preview(self, session_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        session = self.get(session_id)
        if not session.valid_hash:
            raise ValueError("备份哈希校验失败")
        rows = []
        position = 0
        with Path(session.source_path).open("r", encoding="utf-8", errors="replace") as source:
            for line_number, line in enumerate(source, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") not in ("user", "assistant"):
                    continue
                if position >= offset and len(rows) < limit:
                    message = record.get("message") or {}
                    rows.append({
                        "role": record["type"],
                        "timestamp": record.get("timestamp"),
                        "line": line_number,
                        "text": preview_content(message.get("content", ""))[:4000],
                        "blocks": len(message.get("content", [])) if isinstance(message.get("content"), list) else 1,
                    })
                position += 1
                if len(rows) >= limit:
                    break
        return {"items": rows, "offset": offset, "next_offset": offset + len(rows) if offset + len(rows) < session.messages else None}

    def _verify(self, session: Session) -> None:
        if not session.valid_hash or sha256(Path(session.source_path)) != session.sha256:
            raise ValueError(f"备份哈希校验失败：{session.id}")

    def create_transcript(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        self._verify(session)
        sources = [session.id, *session.agent_paths]
        for relative in sources[1:]:
            path = self.backup / relative
            if self.expected.get(relative) != sha256(path):
                raise ValueError(f"子代理记录哈希校验失败：{relative}")
        target = self.app_data / "transcripts" / session.sha256
        transcript = target / "transcript.md"
        index_path = target / "index.json"
        if transcript.exists() and index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if index.get("source_sha256") == session.sha256 and index.get("transcript_sha256") == sha256(transcript):
                return {"transcript": str(transcript), "index": str(index_path), "entries": len(index.get("entries", []))}
        target.mkdir(parents=True, exist_ok=True)
        target.chmod(0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".transcript-", dir=target)
        entries = []
        missing = []
        try:
            with os.fdopen(descriptor, "wb") as output:
                def write(value: str) -> None:
                    output.write(value.encode("utf-8"))
                write(f"# Claude Code 聊天原文\n\n标题：{session.title}\n项目：{session.project}\n")
                write(f"原始记录：{session.source_path}\nSHA-256：{session.sha256}\n\n")
                write("以下按各源文件原始行顺序保留记录。子代理记录单独成节；完整原始 JSONL 是最终校验依据。\n")
                for relative in sources:
                    write(f"\n## 来源：{relative}\n\n")
                    with (self.backup / relative).open("r", encoding="utf-8", errors="replace") as source:
                        for line_number, line in enumerate(source, 1):
                            start = output.tell()
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                write(f"### 第 {line_number} 行：无法解析的原始记录\n\n{line}\n")
                                entries.append({"source": relative, "line": line_number, "offset": start, "type": "invalid"})
                                continue
                            kind = str(record.get("type", "unknown"))
                            entries.append({"source": relative, "line": line_number, "offset": start, "type": kind, "timestamp": record.get("timestamp")})
                            write(f"### 第 {line_number} 行 · {kind} · {record.get('timestamp', '')}\n\n")
                            if kind in ("user", "assistant"):
                                content = (record.get("message") or {}).get("content")
                                if isinstance(content, str):
                                    write(content + "\n\n")
                                elif isinstance(content, list):
                                    for number, block in enumerate(content, 1):
                                        if isinstance(block, dict) and block.get("type") in ("text", "thinking") and isinstance(block.get("text") if block.get("type") == "text" else block.get("thinking"), str):
                                            value = block.get("text") if block.get("type") == "text" else block.get("thinking")
                                            write(f"**内容块 {number} · {block['type']}**\n\n{value}\n\n")
                                        else:
                                            write(f"**内容块 {number} · {block.get('type', 'unknown') if isinstance(block, dict) else 'raw'}**\n\n")
                                            write(json.dumps(block, ensure_ascii=False, indent=2) + "\n\n")
                                else:
                                    write(json.dumps(content, ensure_ascii=False, indent=2) + "\n\n")
                            else:
                                write(json.dumps(record, ensure_ascii=False, indent=2) + "\n\n")
                            missing.extend(_missing_references(record, self.backup))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, transcript)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        index = {
            "source": session.id,
            "source_sha256": session.sha256,
            "associated_sources": sources[1:],
            "transcript_sha256": sha256(transcript),
            "entries": entries,
            "missing_references": sorted(set(missing)),
        }
        atomic_json(index_path, index)
        self._verify(session)
        return {"transcript": str(transcript), "index": str(index_path), "entries": len(entries), "missing_references": index["missing_references"]}


def _missing_references(record: Any, backup: Path) -> list[str]:
    found = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("filePath", "localPath", "imagePath", "attachmentPath") and isinstance(item, str) and item.startswith("/"):
                    if not Path(item).exists() and not (backup / item.lstrip("/")).exists():
                        found.append(item)
                elif isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(record)
    return found


class Staging:
    def __init__(self, index: BackupIndex):
        self.index = index
        self.path = index.app_data / "stage-state.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"entries": [], "created_dirs": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def state(self) -> dict[str, Any]:
        state = self._read()
        state["entries"] = [{**entry, "exists": Path(entry["destination"]).exists()} for entry in state["entries"]]
        return state

    def _mkdir(self, path: Path, state: dict[str, Any]) -> None:
        absent = []
        cursor = path
        while not cursor.exists():
            absent.append(cursor)
            cursor = cursor.parent
        for directory in reversed(absent):
            directory.mkdir(mode=0o700)
            state["created_dirs"].append(str(directory))
            atomic_json(self.path, state)

    def _copy_owned(self, source: Path, destination: Path, state: dict[str, Any]) -> str:
        digest = sha256(source)
        if destination.exists():
            return "identical_existing" if sha256(destination) == digest else "conflict"
        self._mkdir(destination.parent, state)
        descriptor, temporary = tempfile.mkstemp(prefix=".codex-import-", dir=destination.parent)
        os.close(descriptor)
        entry = {"destination": str(destination), "sha256": digest, "temporary": temporary, "owned": True}
        state["entries"].append(entry)
        atomic_json(self.path, state)
        try:
            shutil.copyfile(source, temporary)
            os.chmod(temporary, 0o600)
            if sha256(Path(temporary)) != digest:
                raise ValueError("暂存副本哈希不一致")
            os.link(temporary, destination)
            os.unlink(temporary)
            entry["temporary"] = None
            atomic_json(self.path, state)
            return "staged"
        except FileExistsError:
            state["entries"].remove(entry)
            atomic_json(self.path, state)
            return "conflict"
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def stage(self, ids: Iterable[str]) -> dict[str, Any]:
        ids = list(dict.fromkeys(ids))
        if not ids or len(ids) > 50:
            raise ValueError("每批请选择 1 到 50 条聊天")
        state = self._read()
        if any(Path(e["destination"]).exists() for e in state["entries"]):
            raise ValueError("已有未清理的暂存批次，请先核对并清理")
        state = {"entries": [], "created_dirs": [], "session_ids": ids}
        result = []
        selected_sessions = []
        for session_id in ids:
            session = self.index.get(session_id)
            self.index._verify(session)
            if session.eligibility != "recent":
                raise ValueError(f"已超出近期导入范围：{session.title}")
            if session.status in ("present", "archived"):
                raise ValueError(f"聊天已在 Codex 中：{session.title}")
            selected_sessions.append(session)
        projects = {session.project for session in selected_sessions}
        if len(projects) != 1:
            raise ValueError("官方导入每批只能选择同一个项目的聊天；请先按项目筛选")
        cwd = Path(next(iter(projects)))
        if not cwd.is_dir():
            raise ValueError("原项目目录已不存在；请使用“带原文续聊”")
        state["cwd"] = str(cwd)
        source_history = self.index.backup / "history.jsonl"
        if self.index.expected.get("history.jsonl") != sha256(source_history):
            raise ValueError("提示词历史的备份哈希校验失败")
        for session in selected_sessions:
            destination = self.index.home / ".claude" / session.id
            status = self._copy_owned(Path(session.source_path), destination, state)
            result.append({"id": session.id, "status": status})
        matching = []
        wanted = {s.session_id for s in selected_sessions}
        with source_history.open("r", encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    if json.loads(line).get("sessionId") in wanted:
                        matching.append(line)
                except json.JSONDecodeError:
                    continue
        if matching:
            self.index.app_data.mkdir(parents=True, exist_ok=True)
            history_source = self.index.app_data / "filtered-history.jsonl"
            with history_source.open("w", encoding="utf-8") as output:
                output.writelines(matching)
            history_status = self._copy_owned(history_source, self.index.home / ".claude/history.jsonl", state)
        else:
            history_status = "no_matching_history"
        atomic_json(self.path, state)
        other_sources = 0
        projects_root = self.index.home / ".claude/projects"
        for candidate in projects_root.rglob("*.jsonl") if projects_root.exists() else []:
            if str(candidate) not in {entry["destination"] for entry in state["entries"]}:
                other_sources += 1
        return {"items": result, "history": history_status, "other_sources": other_sources, "command": f"codex -C {shlex.quote(str(cwd))}", "state": self.state()}

    def cleanup(self) -> dict[str, Any]:
        state = self._read()
        removed = []
        retained = []
        for entry in state["entries"]:
            temporary = entry.get("temporary")
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()
            destination = Path(entry["destination"])
            if destination.exists():
                if entry.get("owned") and sha256(destination) == entry["sha256"]:
                    destination.unlink()
                    removed.append(str(destination))
                else:
                    retained.append(str(destination))
        for name in reversed(state.get("created_dirs", [])):
            try:
                Path(name).rmdir()
            except OSError:
                pass
        state["entries"] = [e for e in state["entries"] if e["destination"] in retained]
        state["created_dirs"] = [name for name in state.get("created_dirs", []) if Path(name).exists()]
        atomic_json(self.path, state)
        filtered_history = self.index.app_data / "filtered-history.jsonl"
        if filtered_history.exists():
            filtered_history.unlink()
        return {"removed": removed, "retained": retained}
