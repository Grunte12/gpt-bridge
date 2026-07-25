"""Persistent artifact registration and download responses for the local bridge."""

from __future__ import annotations

import mimetypes
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import quote

from chatgpt_api.api.admin_store import BridgeAdminStore
from chatgpt_api.api.http_utils import send_json


@dataclass(frozen=True, slots=True)
class DownloadFile:
    path: Path
    filename: str
    content_type: str
    created_at: float
    access_token: str


DOWNLOAD_FILES: dict[str, DownloadFile] = {}
DOWNLOAD_FILES_LOCK = threading.Lock()


def register_download_file(
    path: Path,
    content_type: str | None = None,
    public_base_url: str | None = None,
    admin_db_path: Path | None = None,
    kind: str = "file",
    account: str | None = None,
    prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    filename = resolved.name or "download"
    file_id = uuid.uuid4().hex
    detected_content_type = content_type or guess_download_content_type(resolved)
    access_token = secrets.token_urlsafe(32)
    with DOWNLOAD_FILES_LOCK:
        DOWNLOAD_FILES[file_id] = DownloadFile(resolved, filename, detected_content_type, time.time(), access_token)
    relative_url = f"/v1/chatgpt/files/{file_id}/{quote(filename)}?access_token={quote(access_token)}"
    asset = {
        "id": file_id,
        "filename": filename,
        "path": str(resolved),
        "download_url": public_download_url(relative_url, public_base_url),
        "content_type": detected_content_type,
        "bytes": resolved.stat().st_size if resolved.exists() else None,
    }
    if admin_db_path is not None:
        try:
            BridgeAdminStore(admin_db_path).record_artifact(asset, kind=kind, account=account, prompt=prompt, metadata=metadata)
        except Exception:
            pass
    return asset


def download_file_id_from_path(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    return parts[3] if len(parts) >= 4 and parts[:3] == ["v1", "chatgpt", "files"] else None


def send_download_file(
    handler: BaseHTTPRequestHandler,
    file_id: str,
    *,
    admin_db_path: Path | None = None,
    include_body: bool = True,
    access_token: str | None = None,
) -> None:
    with DOWNLOAD_FILES_LOCK:
        entry = DOWNLOAD_FILES.get(file_id)
    if entry is None and admin_db_path is not None:
        artifact = BridgeAdminStore(admin_db_path).get_artifact(file_id)
        if artifact is not None:
            path = Path(str(artifact.get("path") or "")).expanduser()
            if not path.is_file():
                send_json(handler, 410, {"error": {"message": "artifact file is no longer available", "type": "gone"}})
                return
            stored_url = str(artifact.get("download_url") or "")
            stored_token = _access_token_from_url(stored_url)
            entry = DownloadFile(
                path,
                str(artifact.get("filename") or path.name or "download"),
                str(artifact.get("content_type") or guess_download_content_type(path)),
                time.time(),
                stored_token,
            )
            with DOWNLOAD_FILES_LOCK:
                DOWNLOAD_FILES[file_id] = entry
    if entry is None:
        send_json(handler, 404, {"error": {"message": "artifact not found", "type": "not_found"}})
        return
    if not access_token or not secrets.compare_digest(access_token, entry.access_token):
        send_json(handler, 401, {"error": {"message": "artifact access token is missing or invalid", "type": "authentication_error"}})
        return
    if not entry.path.is_file():
        send_json(handler, 410, {"error": {"message": "artifact file is no longer available", "type": "gone"}})
        return
    size = entry.path.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", entry.content_type)
    handler.send_header("Content-Length", str(size))
    handler.send_header("Cache-Control", "private, max-age=31536000")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Disposition", content_disposition(entry.filename))
    handler.end_headers()
    if include_body:
        handler.wfile.write(entry.path.read_bytes())


def public_download_url(relative_url: str, public_base_url: str | None) -> str:
    if not public_base_url:
        return relative_url
    base = public_base_url.rstrip("/")
    return base + relative_url.removeprefix("/v1") if base.endswith("/v1") and relative_url.startswith("/v1/") else base + relative_url


def _access_token_from_url(url: str) -> str:
    match = re.search(r"[?&]access_token=([^&]+)", url)
    return match.group(1) if match else ""


def guess_download_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(path.name)
    if content_type:
        return f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type
    return "application/octet-stream"


def content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
