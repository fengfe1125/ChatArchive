#!/usr/bin/env python3
"""Local-only web UI for selecting Claude Code chats to bring into Codex."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import threading
import uuid
from urllib.parse import parse_qs, urlsplit
import webbrowser

from archive_core import ArchiveCatalog
from archive_export import export_markdown
from account_download import DESTINATION as ACCOUNT_DIR
from codex_bridge import make_account_context_thread, make_context_thread
from import_core import APP_DATA, BACKUP, BackupIndex, Staging


ASSETS = Path(__file__).parent / "assets"


class ImportService:
    def __init__(self, backup: Path = BACKUP, app_data: Path = APP_DATA, home: Path | None = None, account_dir: Path = ACCOUNT_DIR):
        self.index = BackupIndex(backup, app_data, home)
        self.archive = ArchiveCatalog(self.index, account_dir)
        self.staging = Staging(self.index)
        self.token = secrets.token_urlsafe(32)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start_context_job(self, ids: list[str]) -> dict:
        ids = list(dict.fromkeys(ids))
        if not ids or len(ids) > 20:
            raise ValueError("每批请选择 1 到 20 条聊天")
        for session_id in ids:
            session = self.archive.get(session_id)
            if not session["valid_hash"]:
                raise ValueError("备份哈希校验失败")
            if session["source"] == "account" and not session["content_available"]:
                raise ValueError("这条账号聊天在官方导出中没有可恢复正文，不能创建续聊会话")
            if session["status"] in ("present", "archived"):
                raise ValueError(f"聊天已存在于 Codex：{session['title']}")
        with self.lock:
            if any(job["status"] == "running" for job in self.jobs.values()):
                raise ValueError("已有创建任务正在运行")
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"status": "running", "total": len(ids), "completed": 0, "results": [], "errors": []}

        def run() -> None:
            for session_id in ids:
                try:
                    row = self.archive.get(session_id)
                    result = make_context_thread(self.index, row["code_id"]) if row["source"] == "code" else make_account_context_thread(self.archive, session_id)
                    with self.lock:
                        self.jobs[job_id]["results"].append({"id": session_id, **result})
                except Exception as error:
                    with self.lock:
                        self.jobs[job_id]["errors"].append({"id": session_id, "error": str(error)})
                finally:
                    with self.lock:
                        self.jobs[job_id]["completed"] += 1
                    self.archive.reconcile()
            with self.lock:
                self.jobs[job_id]["status"] = "completed"

        threading.Thread(target=run, daemon=True).start()
        return {"job_id": job_id}

    def start_export_job(self, ids: list[str] | None, mode: str) -> dict:
        if ids is not None and (not isinstance(ids, list) or not all(isinstance(x, str) for x in ids)):
            raise ValueError("导出选择无效")
        if mode not in ("readable", "complete"):
            raise ValueError("未知导出模式")
        job_id = uuid.uuid4().hex
        with self.lock:
            self.jobs[job_id] = {"status": "running", "kind": "export", "completed": 0, "total": len(ids) if ids is not None else len(self.archive.sessions), "results": [], "errors": []}

        def run() -> None:
            try:
                result = export_markdown(self.archive, ids, mode)
                with self.lock:
                    self.jobs[job_id]["results"].append(result)
                    self.jobs[job_id]["completed"] = result["count"]
            except Exception as error:
                with self.lock:
                    self.jobs[job_id]["errors"].append({"error": str(error)})
            finally:
                with self.lock:
                    self.jobs[job_id]["status"] = "completed"

        threading.Thread(target=run, daemon=True).start()
        return {"job_id": job_id}


def make_handler(service: ImportService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ClaudeChatImporter/0.1"

        def log_message(self, format: str, *args) -> None:
            pass  # Search terms and conversation identifiers should not enter shell logs.

        def _headers(self, status: int, kind: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")

        def _json(self, value: object, status: int = 200) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(data))
            self.end_headers()
            self.wfile.write(data)

        def _error(self, message: str, status: int = 400) -> None:
            self._json({"error": message}, status)

        def _authenticated(self) -> bool:
            host = self.headers.get("Host", "")
            if host not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
                return False
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                return False
            return cookie.get("import_token") is not None and secrets.compare_digest(cookie["import_token"].value, service.token)

        def _csrf(self) -> bool:
            origin = self.headers.get("Origin", "")
            allowed = (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
            return origin in allowed and secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), service.token)

        def _query(self) -> tuple[str, dict[str, list[str]]]:
            parsed = urlsplit(self.path)
            return parsed.path, parse_qs(parsed.query)

        def _param(self, params: dict[str, list[str]], key: str, default: str = "") -> str:
            return params.get(key, [default])[0]

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("请求数据大小无效")
            result = json.loads(self.rfile.read(length))
            if not isinstance(result, dict):
                raise ValueError("请求必须是对象")
            return result

        def do_GET(self) -> None:
            path, params = self._query()
            if path == "/" and self._param(params, "token") == service.token:
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"import_token={service.token}; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            if not self._authenticated():
                self._error("未授权；请使用启动时显示的本地链接", 403)
                return
            try:
                if path == "/api/info":
                    rows = list(service.index.sessions.values())
                    self._json({
                        "backup": str(service.index.backup),
                        "total": len(rows),
                        "recent": sum(s.eligibility == "recent" for s in rows),
                        "older": sum(s.eligibility == "older" for s in rows),
                        "unknown": sum(s.eligibility == "unknown" for s in rows),
                        "invalid": sum(not s.valid_hash for s in rows),
                        "projects": sorted(set(s.project for s in rows)),
                        "csrf": service.token,
                    })
                elif path == "/api/archive/info":
                    rows = list(service.archive.sessions.values())
                    projects = {}
                    for row in rows:
                        key = (row["source"], row["project"])
                        projects[key] = projects.get(key, 0) + 1
                    self._json({"total": len(rows), "code": sum(r["source"] == "code" for r in rows),
                                "account": sum(r["source"] == "account" for r in rows),
                                "account_status": service.archive.account_status,
                                "projects": [{"source": key[0], "path": key[1], "count": count} for key, count in sorted(projects.items())],
                                "csrf": service.token})
                elif path == "/api/archive/sessions":
                    page = min(max(int(self._param(params, "page", "1")), 1), 10000)
                    self._json(service.archive.list(query=self._param(params, "query"), project=self._param(params, "project"),
                        source=self._param(params, "source"), status=self._param(params, "status"), code=self._param(params, "code"),
                        review=self._param(params, "review"), date_from=self._param(params, "from"), date_to=self._param(params, "to"), page=page))
                elif path == "/api/archive/messages":
                    offset = min(max(int(self._param(params, "offset", "0")), 0), 10000000)
                    self._json(service.archive.messages(self._param(params, "id"), offset, 20))
                elif path == "/api/archive/code":
                    self._json({"items": service.archive.code_items(self._param(params, "id"))})
                elif path == "/api/archive/code/content":
                    self._json(service.archive.code_content(self._param(params, "id"), self._param(params, "item")))
                elif path == "/api/archive/raw/content":
                    self._json(service.archive.raw_content(self._param(params, "id"), int(self._param(params, "line", "0")), int(self._param(params, "offset", "0"))))
                elif path == "/api/archive/raw":
                    offset = min(max(int(self._param(params, "offset", "0")), 0), 10000000)
                    self._json(service.archive.raw(self._param(params, "id"), offset))
                elif path == "/api/sessions":
                    page = min(max(int(self._param(params, "page", "1")), 1), 10000)
                    self._json(service.index.list(
                        query=self._param(params, "query"), project=self._param(params, "project"),
                        status=self._param(params, "status"), page=page, size=20,
                    ))
                elif path == "/api/preview":
                    offset = min(max(int(self._param(params, "offset", "0")), 0), 10000000)
                    self._json(service.index.preview(self._param(params, "id"), offset, 20))
                elif path == "/api/stage":
                    self._json(service.staging.state())
                elif path == "/api/job":
                    with service.lock:
                        job = service.jobs.get(self._param(params, "id"))
                        if job is None:
                            raise ValueError("未知任务")
                        self._json(dict(job))
                elif path in ("/", "/app.js", "/styles.css", "/tokens.css"):
                    name = "index.html" if path == "/" else path[1:]
                    data = (ASSETS / name).read_bytes()
                    kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    self._headers(200, kind + "; charset=utf-8", len(data))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._error("未找到", 404)
            except (ValueError, OSError) as error:
                self._error(str(error))

        def do_POST(self) -> None:
            if not self._authenticated() or not self._csrf():
                self._error("未授权", 403)
                return
            path, _ = self._query()
            try:
                body = self._body()
                if path == "/api/reconcile":
                    service.archive.reconcile()
                    self._json({"ok": True})
                elif path == "/api/refresh":
                    service.archive.refresh()
                    self._json({"ok": True})
                elif path == "/api/archive/review":
                    service.archive.set_review(str(body.get("id", "")), str(body.get("review", "")))
                    self._json({"ok": True})
                elif path == "/api/archive/export":
                    self._json(service.start_export_job(body.get("ids"), str(body.get("mode", "readable"))))
                elif path == "/api/stage":
                    ids = body.get("ids")
                    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
                        raise ValueError("请选择聊天")
                    self._json(service.staging.stage(ids))
                elif path == "/api/stage/cleanup":
                    self._json(service.staging.cleanup())
                elif path == "/api/context":
                    ids = body.get("ids")
                    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
                        raise ValueError("请选择聊天")
                    self._json(service.start_context_job(ids))
                else:
                    self._error("未找到", 404)
            except (ValueError, OSError, RuntimeError) as error:
                self._error(str(error))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code → Codex 本地聊天导入 UI")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--backup", type=Path, default=BACKUP)
    parser.add_argument("--data", type=Path, default=APP_DATA)
    parser.add_argument("--account-dir", type=Path, default=ACCOUNT_DIR)
    args = parser.parse_args()
    os.umask(0o077)
    service = ImportService(args.backup, args.data, account_dir=args.account_dir)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    url = f"http://127.0.0.1:{server.server_port}/?token={service.token}"
    print(f"本地界面：{url}", flush=True)
    print("按 Ctrl+C 退出。聊天原文不会上传。", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
