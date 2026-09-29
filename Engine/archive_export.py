"""Export readable or full Markdown copies while preserving source backups."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import uuid

from account_download import digest_file
from archive_core import ArchiveCatalog
from import_core import atomic_json, sha256


def export_markdown(catalog: ArchiveCatalog, ids: list[str] | None, mode: str = "readable", destination: Path | None = None) -> dict:
    if mode not in ("readable", "complete"):
        raise ValueError("未知的导出模式")
    selected = list(dict.fromkeys(ids if ids is not None else catalog.sessions.keys()))
    if not selected:
        raise ValueError("没有可导出的聊天")
    base = (destination or (catalog.data / "exports")) / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    base.mkdir(parents=True, exist_ok=False)
    base.chmod(0o700)
    entries = []
    for session_id in selected:
        row = catalog.get(session_id)
        if not row["valid_hash"]:
            raise ValueError("备份哈希校验失败：" + session_id)
        if row["source"] == "code":
            if sha256(Path(row["source_path"])) != row["sha256"]:
                raise ValueError("源聊天已变化：" + session_id)
        elif digest_file(catalog.account_dir / "conversations-000.zip") != row["archive_sha256"]:
            raise ValueError("账号导出 ZIP 已变化：" + session_id)
        filename = row["source"] + "-" + __import__("hashlib").sha256(session_id.encode()).hexdigest()[:16] + ".md"
        path = base / filename
        if mode == "complete" and row["source"] == "code":
            original = catalog.code.create_transcript(row["code_id"])["transcript"]
            shutil.copyfile(original, path)
        elif mode == "complete":
            raw_path = Path(row["raw_cache_file"])
            if sha256(raw_path) != row["raw_cache_sha256"]:
                raise ValueError("账号原始聊天缓存校验失败：" + session_id)
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            with path.open("w", encoding="utf-8") as output:
                output.write(f"# {row['title']}\n\n来源：{row['source_path']}\n原始 ZIP SHA-256：{row['archive_sha256']}\n\n")
                output.write("以下是该聊天在账号导出中的完整 JSON 记录。\n\n")
                output.write("````json\n" + json.dumps(raw, ensure_ascii=False, indent=2) + "\n````\n")
        else:
            with path.open("w", encoding="utf-8") as output:
                output.write(f"# {row['title']}\n\n来源：{row['source_path']}\n项目：{row['project']}\n")
                output.write(f"源内容 SHA-256：{row['sha256']}\n\n")
                output.write("阅读版保留完整对话正文；工具、思考和系统记录请查原始备份或导出完整记录版。\n\n")
                for event in catalog.messages_all(session_id):
                    output.write(f"## {'用户' if event['role'] == 'user' else 'Claude'}")
                    if event.get("timestamp"):
                        output.write(" · " + str(event["timestamp"]))
                    output.write("\n\n")
                    if event["text"]:
                        output.write(event["text"] + "\n\n")
                    for media in event.get("media", []):
                        availability = "可恢复" if media.get("available") in (True, "true") else "原文未包含可恢复内容"
                        output.write(f"[附件：{media.get('name', '附件')}；{availability}]\n\n")
                        if media.get("text"):
                            output.write("#### 附件提取文本\n\n" + media["text"] + "\n\n")
        entry = {"id": session_id, "source": row["source"], "title": row["title"], "source_path": row["source_path"],
                 "source_sha256": row["sha256"], "export_file": filename, "export_sha256": sha256(path), "bytes": path.stat().st_size}
        if row["source"] == "account":
            entry["archive_sha256"] = row["archive_sha256"]
        entries.append(entry)
    atomic_json(base / "manifest.json", {"mode": mode, "count": len(entries), "entries": entries})
    return {"directory": str(base), "count": len(entries), "manifest": str(base / "manifest.json")}
