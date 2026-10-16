"""Opt-in, localhost-only image worker for a user-paired ChatGPT extension.

No ChatGPT credentials or internal APIs are handled here. A claimed job is never
redelivered, including after restart: uncertain submissions require human review.
Run separately from existing Bridge services: python -m chatgpt_api.extension_bridge.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PIL import Image

MAX_IMAGE = 25 * 1024 * 1024
TERMINAL = {"complete", "failed", "interrupted"}
PORT = 18767


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None  # Never forward local pairing authorization to another URL.


class ExtensionClient:
    """A stdio MCP client shares the existing local worker, never its queue files."""

    def __init__(self, token: str):
        self.token = token
        self.http = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, action: str, data: dict) -> dict:
        request = Request(f"http://127.0.0.1:{PORT}/agent/{action}",
                          data=json.dumps(data).encode(), method="POST",
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"})
        try:
            with self.http.open(request, timeout=10) as response:
                raw = response.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                raise ValueError("oversized worker response")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("invalid worker response")
            return result
        except (HTTPError, URLError, OSError, ValueError) as from_error:
            raise ValueError("Local extension worker unavailable or request rejected; inspect status before retrying. No automatic retry.") from from_error

    def status(self, job_id: str = "") -> dict:
        return self.call("status", {"job_id": job_id})

    def submit(self, prompt: str, expected_model: str) -> dict:
        return self.call("image", {"prompt": prompt, "expected_model": expected_model})

    def resolve(self, job_id: str) -> dict:
        return self.call("resolve", {"job_id": job_id, "inspected_chatgpt": True})

    def confirm_delete(self, job_id: str, owner_confirmed: bool = False) -> dict:
        return self.call("confirm-delete", {"job_id": job_id, "owner_confirmed": owner_confirmed})


class ExtensionQueue:
    def __init__(self, root: Path, account: str):
        if root.is_symlink():
            raise ValueError("data directory must not be a symlink")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.account = account
        self.lock = threading.RLock()
        self.client = None
        self.jobs: dict[str, dict] = {}
        for path in self.root.glob("*/state.json"):
            if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 70000:
                continue
            try:
                record = json.loads(path.read_text())
            except (ValueError, OSError):
                continue
            if not isinstance(record, dict) or record.get("account") != account:
                continue
            if record.get("job_id") != path.parent.name or not re.fullmatch(r"[a-f0-9]{32}", path.parent.name):
                continue
            self.jobs[path.parent.name] = record
            if record.get("state") not in TERMINAL:
                record.update(state="interrupted", error="Server restarted; inspect ChatGPT before resubmitting.")
                self._save(record)
            elif record.get("cleanup_status") in {"pending", "confirmation_required"}:
                record.update(cleanup_status="failed", cleanup_confirmation="invalidated",
                              cleanup_error="Server restarted before cleanup was verified; inspect the chat, do not repeat deletion automatically.")
                self._save(record)

    def _save(self, job):
        directory = self.root / job["job_id"]
        directory.mkdir(mode=0o700, exist_ok=True)
        temporary = directory / "state.tmp"
        temporary.write_text(json.dumps(job))
        temporary.chmod(0o600)
        temporary.replace(directory / "state.json")

    def pair(self, client_id: str, account: str, visible_model: str = "") -> dict:
        if account != self.account or not isinstance(client_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", client_id):
            raise ValueError("account or client identity mismatch")
        if not isinstance(visible_model, str) or len(visible_model) > 100:
            raise ValueError("invalid visible model label")
        with self.lock:
            if any(j["state"] not in TERMINAL or j.get("cleanup_status") in {"pending", "confirmation_required"} for j in self.jobs.values()):
                raise ValueError("finish or resolve the current job before pairing again")
            self.client = {"client_id": client_id, "seen": time.monotonic(), "visible_model": visible_model,
                           "tab_ready": True}
            return {"paired": True, "account": self.account, "identity": "owner-confirmed, not independently verified"}

    def heartbeat(self, client_id: str, account: str, visible_model: str = "Create image",
                  tab_ready: bool = False) -> dict:
        """Reconnect the already-authorized local extension, never replay old work."""
        if account != self.account or type(tab_ready) is not bool:
            raise ValueError("account or readiness mismatch")
        if not isinstance(visible_model, str) or visible_model != "Create image":
            raise ValueError("native Create image mode is required")
        with self.lock:
            if self.client is None:
                self.pair(client_id, account, visible_model)
            else:
                self._client(client_id)
            self.client.update(visible_model=visible_model, tab_ready=tab_ready)
            return self.status()

    def _client(self, client_id):
        if not isinstance(client_id, str) or not self.client or not hmac.compare_digest(self.client["client_id"], client_id):
            raise ValueError("extension is not paired")
        self.client["seen"] = time.monotonic()

    def submit(self, prompt: str, expected_model: str) -> dict:
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 16000:
            raise ValueError("prompt must contain 1..16000 characters")
        if expected_model != "Create image":
            raise ValueError('expected_model must be exactly "Create image"')
        with self.lock:
            if not self.client or time.monotonic() - self.client["seen"] > 90:
                raise ValueError("pair a logged-in ChatGPT tab and wait for its heartbeat first")
            if any(j["state"] not in TERMINAL or j.get("cleanup_status") in {"pending", "confirmation_required"} for j in self.jobs.values()):
                raise ValueError("one image job at a time; inspect existing job before resubmitting")
            job = {"job_id": uuid.uuid4().hex, "state": "queued", "prompt": prompt, "account": self.account,
                   "expected_model": expected_model.strip(), "client_id": self.client["client_id"]}
            self.jobs[job["job_id"]] = job
            self._save(job)
            return self.status(job["job_id"])

    def claim(self, client_id: str) -> dict:
        with self.lock:
            self._client(client_id)
            for job in self.jobs.values():
                if job["state"] == "queued" and job["client_id"] == client_id:
                    job["state"] = "claimed"
                    self._save(job)  # Persist BEFORE delivery. Never repeat on uncertain response.
                    return {k: job[k] for k in ("job_id", "prompt", "expected_model")}
            return {}

    def result(self, client_id: str, job_id: str, *, image_base64: str | None = None,
               error: str | None = None, source: str = "rendered-image", cleanup_pending: bool = False,
               chat_path: str | None = None) -> dict:
        if type(cleanup_pending) is not bool:
            raise ValueError("invalid cleanup flag")
        if chat_path is not None and (not isinstance(chat_path, str) or not re.fullmatch(r"/c/[a-f0-9-]{36}", chat_path)):
            raise ValueError("invalid generated chat path")
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if not job or job["client_id"] != client_id or job["state"] != "claimed":
                raise ValueError("job is not claimed by this extension; result was not accepted")
            if error is not None:
                job.update(state="failed", error=str(error)[:500])
            else:
                if not image_base64 or len(image_base64) > (MAX_IMAGE * 4 // 3 + 8):
                    raise ValueError("missing or oversized image")
                raw = base64.b64decode(image_base64, validate=True)
                if len(raw) > MAX_IMAGE:
                    raise ValueError("image exceeds 25 MiB")
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"} or min(image.size) < 512 or image.width * image.height > 40_000_000:
                        raise ValueError("not a supported generated image of at least 512px")
                    image.verify()
                    suffix = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image.format]
                    dimensions = list(image.size)
                path = self.root / job_id / ("image." + suffix)
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(raw)
                job.update(state="complete", image_path=str(path), dimensions=dimensions,
                           sha256=hashlib.sha256(raw).hexdigest(), source=source,
                           cleanup_status="pending" if cleanup_pending else "not_requested",
                           quality_note="Rendered asset; original download resolution not verified.")
                if chat_path is not None:
                    job["chat_path"] = chat_path
            self._save(job)
            return self.status(job_id)

    def confirm_delete(self, job_id: str, owner_confirmed: bool = False) -> dict:
        """Authorize this one pending native dialog only after actual owner approval."""
        if owner_confirmed is not True:
            raise ValueError("actual owner confirmation is required for this exact chat at action time")
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["state"] != "complete" or job.get("cleanup_status") != "confirmation_required" or not job.get("chat_path"):
                raise ValueError("this saved-image chat is not awaiting deletion confirmation")
            if not self.client or job["client_id"] != self.client["client_id"] or time.monotonic() - self.client["seen"] > 90:
                raise ValueError("the original paired extension must be online")
            if job.get("cleanup_confirmation"):
                raise ValueError("deletion confirmation is single-use; inspect status, never repeat")
            job["cleanup_confirmation"] = "requested"
            self._save(job)
            return self.status(job_id)

    def claim_delete_confirmation(self, client_id: str, job_id: str) -> dict:
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if not job or job["client_id"] != client_id or job["state"] != "complete" or job.get("cleanup_status") != "confirmation_required":
                raise ValueError("only the original saved-image dialog can claim confirmation")
            confirmed = job.get("cleanup_confirmation") == "requested"
            if confirmed:
                job["cleanup_confirmation"] = "consumed"
                self._save(job)  # Consume before delivery; never repeat an uncertain delete.
            return {"confirmed": confirmed}

    def cleanup(self, client_id: str, job_id: str, cleanup_status: str, error: str = "") -> dict:
        """Record native deletion confirmation/outcome without changing a saved image."""
        if cleanup_status not in {"confirmation_required", "deleted", "failed"} or not isinstance(error, str):
            raise ValueError("invalid cleanup outcome")
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if not job or job["client_id"] != client_id or job["state"] != "complete" or job.get("cleanup_status") not in {"pending", "confirmation_required"}:
                raise ValueError("cleanup is not pending for this extension's saved image")
            if cleanup_status == "confirmation_required" and job["cleanup_status"] != "pending":
                raise ValueError("deletion confirmation is already pending")
            if cleanup_status == "deleted" and job["cleanup_status"] != "confirmation_required":
                raise ValueError("deletion must follow the native confirmation step")
            job.update(cleanup_status=cleanup_status)
            if cleanup_status == "failed":
                job["cleanup_error"] = error[:500]
            self._save(job)
            return self.status(job_id)

    def status(self, job_id: str = "") -> dict:
        with self.lock:
            if not job_id:
                return {"account": self.account, "paired": bool(self.client),
                        "account_binding": "owner-confirmed, not independently verified",
                        "transport": "extension-native-ui",
                        "visible_model": self.client["visible_model"] if self.client else None,
                        "tab_ready": bool(self.client and self.client["tab_ready"]),
                        "extension_online": bool(self.client and time.monotonic() - self.client["seen"] <= 90),
                        "jobs": [{k: j[k] for k in ("job_id", "state", "cleanup_status", "chat_path") if k in j}
                                 for j in list(self.jobs.values())[-10:]]}
            if job_id not in self.jobs:
                raise ValueError("unknown job")
            return {k: v for k, v in self.jobs[job_id].items() if k not in {"prompt", "client_id"}}

    def client_status(self, client_id: str, job_id: str) -> dict:
        """Let the original extension clear terminal work, including after restart."""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or not isinstance(client_id, str) or not hmac.compare_digest(job["client_id"], client_id):
                raise ValueError("job does not belong to this extension")
            return self.status(job_id)

    def resolve(self, job_id: str) -> dict:
        """Explicit operator action after inspecting the upstream conversation."""
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("unknown job")
            if self.jobs[job_id]["state"] not in TERMINAL:
                self.jobs[job_id].update(state="interrupted", error="Operator resolved uncertain work; no automatic resubmission.")
                self._save(self.jobs[job_id])
            return self.status(job_id)


def make_handler(queue: ExtensionQueue, token: str, port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log prompts, request bodies or credentials.

        def permitted_origin(self):
            origin = self.headers.get("Origin", "")
            return not origin or bool(re.fullmatch(r"chrome-extension://[a-p]{32}", origin))

        def reply(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status)
            if self.permitted_origin() and self.headers.get("Origin"):
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Vary", "Origin")
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def safe_request(self):
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"} and self.permitted_origin()

        def do_OPTIONS(self):
            if not self.safe_request():
                return self.reply(403, {"error": "origin or host rejected"})
            self.send_response(204)
            if self.headers.get("Origin"):
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.end_headers()

        def do_POST(self):
            if not self.safe_request():
                return self.reply(403, {"error": "origin or host rejected"})
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return self.reply(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_IMAGE * 4 // 3 + 4096:
                    return self.reply(413, {"error": "request too large"})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("request must be an object")
                if self.path == "/pair":
                    result = queue.pair(data["client_id"], data["account"], data.get("visible_model", ""))
                elif self.path == "/heartbeat":
                    result = queue.heartbeat(**data)
                elif self.path == "/next":
                    result = queue.claim(data["client_id"])
                elif self.path == "/result":
                    result = queue.result(**data)
                elif self.path == "/cleanup":
                    result = queue.cleanup(**data)
                elif self.path == "/cleanup-confirmation":
                    result = queue.claim_delete_confirmation(**data)
                elif self.path == "/state":
                    result = queue.client_status(data["client_id"], data["job_id"])
                elif self.path == "/agent/status":
                    result = queue.status(**data)
                elif self.path == "/agent/image":
                    result = queue.submit(**data)
                elif self.path == "/agent/confirm-delete":
                    result = queue.confirm_delete(**data)
                elif self.path == "/agent/resolve":
                    if data.get("inspected_chatgpt") is not True:
                        raise ValueError("inspect ChatGPT before resolving uncertain work")
                    result = queue.resolve(data["job_id"])
                else:
                    return self.reply(404, {"error": "unknown route"})
                self.reply(200, result)
            except (ValueError, KeyError, TypeError, OSError):
                self.reply(400, {"error": "invalid request or job state; inspect MCP status"})
    return Handler


def create_mcp(queue):
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("GPT Bridge Extension", instructions="Opt-in image generation via one owner-paired ChatGPT tab. No direct HTTP fallback. Check status first; never retry uncertain jobs.")

    @server.tool()
    def extension_status(job_id: str = "") -> dict:
        """Check a saved image job. confirmation_required blocks new images; show its chat_path and request owner approval, then call extension_confirm_delete once. deleted confirms cleanup. Cleanup failure never means regenerate the saved image."""
        return queue.status(job_id)

    @server.tool()
    def extension_image(prompt: str, expected_model: str) -> dict:
        """Generate ONE image on second. Use expected_model='Create image'. The paired extension prepares a fresh native image chat for this new job; it never clears drafts, interrupts running work, or retries uncertain submissions. Check status first; pairing and extension_online are required, tab_ready may be false."""
        return queue.submit(prompt, expected_model)

    @server.tool()
    def extension_confirm_delete(job_id: str, owner_confirmed: bool = False) -> dict:
        """Permanently delete only this saved-image chat via MCP/extension, without browser-control tools. Require actual owner approval at action time for the exact job and chat_path; never infer it from a cleanup preference. Pass owner_confirmed=true only after that approval. Single-use: poll status, never retry uncertain deletion."""
        return queue.confirm_delete(job_id, owner_confirmed)

    @server.tool()
    def extension_resolve(job_id: str, inspected_chatgpt: bool = False) -> dict:
        """Release uncertain work ONLY after the operator has inspected ChatGPT. Does not cancel or resend upstream work."""
        if not inspected_chatgpt:
            raise ValueError("inspect ChatGPT before resolving uncertain work")
        return queue.resolve(job_id)

    return server


def read_token(root: Path) -> str:
    token_path = root / "extension-token"
    if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
        raise ValueError("extension token file must be private and not a symlink")
    token = token_path.read_text().strip()
    if len(token) < 32:
        raise ValueError("invalid local pairing token")
    return token


def main():
    parser = argparse.ArgumentParser(description="Opt-in GPT Bridge extension MCP (no browser-control tools)")
    parser.add_argument("--account", required=True, choices=["second"],
                        help="Experimental runtime is restricted to the owner's second account")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".local/share/gpt-bridge/extension/second")
    parser.add_argument("--connect", action="store_true",
                        help="Share an already running local extension worker; do not create another queue or listener")
    args = parser.parse_args()
    if args.data_dir.is_symlink():
        parser.error("data directory must not be a symlink")
    root = args.data_dir.resolve()
    if args.connect:
        try:
            client = ExtensionClient(read_token(root))
        except (ValueError, OSError) as error:
            parser.error(str(error))
        create_mcp(client).run(transport="stdio")
        return
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl
    lock = (root / ".lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("another extension MCP owns this data directory")
    queue = ExtensionQueue(root, args.account)
    token_path = queue.root / "extension-token"
    if not token_path.exists():
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(secrets.token_urlsafe(32))
    try:
        token = read_token(root)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    server = create_mcp(queue)

    http = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(queue, token, PORT))
    http.daemon_threads = True
    threading.Thread(target=http.serve_forever, daemon=True).start()
    import sys
    print(f"Extension worker ready on localhost:18767; local pairing token: {token_path}", file=sys.stderr)
    try:
        server.run(transport="stdio")
    finally:
        http.shutdown()
        http.server_close()


if __name__ == "__main__":
    main()
