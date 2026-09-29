"""Download and verify one-use Claude account export archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile


MANIFEST = Path.home() / "Library/Application Support/ChatArchive/unconfigured-manifest.json"
DESTINATION = Path.home() / "Library/Application Support/ChatArchive/unconfigured-account"


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP 校验失败：{bad}")


def download(manifest_path: Path = MANIFEST, destination: Path = DESTINATION) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("data_files"), list):
        raise ValueError("导出清单没有 data_files")
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    state_path = destination / "download-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"created_at": manifest.get("created_at"), "files": {}}
    for item in manifest["data_files"]:
        filename = item["filename"]
        if Path(filename).name != filename or not filename.endswith(".zip"):
            raise ValueError("导出文件名无效")
        url = item["export_url"]
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "claude.ai":
            raise ValueError("导出链接不是 claude.ai 的 HTTPS 链接")
        target = destination / filename
        partial = destination / (filename + ".partial")
        if target.exists():
            verify_zip(target)
            state["files"][filename] = {"status": "verified", "bytes": target.stat().st_size, "sha256": digest_file(target), "category": item["category"]}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            print(f"{filename}: 已核验现有文件", flush=True)
            continue
        if partial.exists():
            state["files"][filename] = {"status": "incomplete", "bytes": partial.stat().st_size, "category": item["category"]}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            print(f"{filename}: 存在未完成文件，跳过一次性链接", flush=True)
            continue
        state["files"][filename] = {"status": "downloading", "category": item["category"]}
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 ClaudeArchive/1.0"})
            with urlopen(request, timeout=90) as response, partial.open("xb") as output:
                expected = response.headers.get("Content-Length")
                count = 0
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    count += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if expected is not None and count != int(expected):
                raise ValueError("下载字节数与响应标注不符")
            verify_zip(partial)
            digest = digest_file(partial)
            os.replace(partial, target)
            state["files"][filename] = {"status": "verified", "bytes": count, "sha256": digest, "category": item["category"]}
            print(f"{filename}: 已下载并核验 ({count} bytes)", flush=True)
        except Exception as error:
            state["files"][filename] = {"status": "incomplete", "bytes": partial.stat().st_size if partial.exists() else 0, "error": str(error), "category": item["category"]}
            print(f"{filename}: 下载或核验失败：{error}", flush=True)
        finally:
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            state_path.chmod(0o600)
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    args = parser.parse_args()
    result = download(args.manifest, args.destination)
    print("已核验", sum(item["status"] == "verified" for item in result["files"].values()), "/", len(result["files"]), flush=True)
