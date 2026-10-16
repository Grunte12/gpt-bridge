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
import stat
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictBool

MAX_IMAGE = 25 * 1024 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024  # Local transport budget, NOT a ChatGPT upload limit.
TERMINAL = {"complete", "failed", "interrupted"}
PORT = 18767


class LocalImageInput(BaseModel):
    """One real local upload, in attachment order; never a filename-only reference."""
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(description="Absolute regular local PNG, JPEG or WebP file; no URLs or symlinks.")
    role: Literal["source", "reference"] = "reference"
    description: str = Field(min_length=1, max_length=200,
                             description="What this image controls, e.g. Goofy identity or cafe staging.")


def read_local_image(path: str) -> bytes:
    """Open every path component without following symlinks; reject special files."""
    if not isinstance(path, str) or not Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("image path must be absolute and local")
    parts = Path(path).parts[1:]
    if not parts:
        raise ValueError("image path must be a regular file")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_INPUT_BYTES:
                raise ValueError("input must be a regular image within the 8 MiB transport budget")
            raw = source.read(MAX_INPUT_BYTES + 1)
            if not raw or len(raw) > MAX_INPUT_BYTES:
                raise ValueError("input exceeds the 8 MiB transport budget")
            return raw
    finally:
        os.close(directory)


def validated_inputs(mode: str, images) -> list[tuple[dict, bytes]]:
    if mode not in {"create", "edit"}:
        raise ValueError("mode must be create or edit")
    if images is None:
        images = []
    if not isinstance(images, list):
        raise ValueError("images must be an ordered list")
    inputs = [item if isinstance(item, LocalImageInput) else LocalImageInput.model_validate(item) for item in images]
    if mode == "edit" and not any(item.role == "source" for item in inputs):
        raise ValueError("edit requires at least one source image")
    if mode == "create" and any(item.role == "source" for item in inputs):
        raise ValueError("source images require edit mode; create accepts references")
    result, total = [], 0
    formats = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "WEBP": ("webp", "image/webp")}
    for index, item in enumerate(inputs, 1):
        if not item.description.strip() or any(ord(char) < 32 for char in item.description):
            raise ValueError("image description must be a short single line")
        raw = read_local_image(item.path)
        total += len(raw)
        if total > MAX_INPUT_BYTES:
            raise ValueError("combined inputs exceed the 8 MiB transport budget")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if (image.format not in formats or getattr(image, "n_frames", 1) != 1 or
                        min(image.size) < 1 or max(image.size) > 8192 or image.width * image.height > 40_000_000):
                    raise ValueError("unsupported input image")
                suffix, mime = formats[image.format]
                dimensions = list(image.size)
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
        except (OSError, Image.DecompressionBombError) as error:
            raise ValueError("input is not a valid static PNG, JPEG or WebP") from error
        result.append(({"order": index, "role": item.role, "description": item.description.strip(),
                        "name": f"input-{index:03d}.{suffix}", "mime": mime, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(), "dimensions": dimensions}, raw))
        if len(json.dumps([metadata for metadata, _raw in result]).encode()) > 48 * 1024:
            raise ValueError("input metadata exceeds the 48 KiB Bridge state budget")
    return result


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

    def submit(self, prompt: str, expected_model: str, mode: str = "create", images=None,
               preflight_only: bool = False, clear_preflight_uploads: bool = False) -> dict:
        return self.call("image", {"prompt": prompt, "expected_model": expected_model, "mode": mode,
                                   "images": [item.model_dump() if isinstance(item, LocalImageInput) else item
                                              for item in (images or [])], "preflight_only": preflight_only,
                                   **({"clear_preflight_uploads": clear_preflight_uploads} if clear_preflight_uploads is not False else {})})

    def resolve(self, job_id: str, clear_preflight_uploads: bool = False,
                clear_failed_uploads: bool = False, native_upload_names: list[str] | None = None) -> dict:
        return self.call("resolve", {"job_id": job_id, "inspected_chatgpt": True,
                                    **({"clear_preflight_uploads": clear_preflight_uploads} if clear_preflight_uploads is not False else {}),
                                    **({"clear_failed_uploads": clear_failed_uploads} if clear_failed_uploads is not False else {}),
                                    **({"native_upload_names": native_upload_names} if native_upload_names is not None else {})})

    def confirm_delete(self, job_id: str, owner_confirmed: bool = False) -> dict:
        return self.call("confirm-delete", {"job_id": job_id, "owner_confirmed": owner_confirmed})


class ExtensionQueue:
    def __init__(self, root: Path, account: str, *, auto_delete_saved_chats: bool = False):
        if type(auto_delete_saved_chats) is not bool:
            raise ValueError("invalid automatic cleanup policy")
        if root.is_symlink():
            raise ValueError("data directory must not be a symlink")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.account = account
        self.auto_delete_saved_chats = auto_delete_saved_chats
        self.lock = threading.RLock()
        self.client = None
        self.jobs: dict[str, dict] = {}
        for path in self.root.glob("*/state.json"):
            if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 256 * 1024:
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

    def pair(self, client_id: str, account: str, visible_model: str = "", input_protocol: int = 0) -> dict:
        if account != self.account or not isinstance(client_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", client_id):
            raise ValueError("account or client identity mismatch")
        if not isinstance(visible_model, str) or len(visible_model) > 100:
            raise ValueError("invalid visible model label")
        if type(input_protocol) is not int or input_protocol not in {0, 1, 2, 3, 4}:
            raise ValueError("invalid input protocol")
        with self.lock:
            if any(j["state"] not in TERMINAL or j.get("cleanup_status") in {"pending", "confirmation_required"} for j in self.jobs.values()):
                raise ValueError("finish or resolve the current job before pairing again")
            self.client = {"client_id": client_id, "seen": time.monotonic(), "visible_model": visible_model,
                           "tab_ready": True, "input_protocol": input_protocol}
            return {"paired": True, "account": self.account, "identity": "owner-confirmed, not independently verified"}

    def heartbeat(self, client_id: str, account: str, visible_model: str = "Create image",
                  tab_ready: bool = False, input_protocol: int = 0,
                  tab_idle: bool | None = None, tab_error: str = "",
                  worker_version: str = "", content_receiver: str = "unreported",
                  receiver_error: str = "", upload_dom: dict | None = None) -> dict:
        """Reconnect the already-authorized local extension, never replay old work."""
        if account != self.account or type(tab_ready) is not bool:
            raise ValueError("account or readiness mismatch")
        if not isinstance(visible_model, str) or visible_model != "Create image":
            raise ValueError("native Create image mode is required")
        if type(input_protocol) is not int or input_protocol not in {0, 1, 2, 3, 4}:
            raise ValueError("invalid input protocol")
        if (tab_idle is not None and type(tab_idle) is not bool) or not isinstance(tab_error, str) or len(tab_error) > 300:
            raise ValueError("invalid tab diagnostic")
        if (not isinstance(worker_version, str) or len(worker_version) > 32 or
                (worker_version and not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", worker_version))):
            raise ValueError("invalid worker version")
        if not isinstance(content_receiver, str) or content_receiver not in {
                "unreported", "available", "tab_missing", "wrong_origin", "unavailable", "invalid_reply"}:
            raise ValueError("invalid content receiver diagnostic")
        if not isinstance(receiver_error, str) or receiver_error not in {
                "", "tab_missing", "wrong_origin", "no_receiver", "port_closed", "message_failed", "invalid_reply"}:
            raise ValueError("invalid receiver error diagnostic")
        upload_counts = {"file_inputs", "form_file_inputs", "image_inputs", "form_image_inputs",
                         "multiple_image_inputs", "unrestricted_inputs", "attachment_cards"}
        if upload_dom is not None and (not isinstance(upload_dom, dict) or
                set(upload_dom) != upload_counts | {"editor_form"} or type(upload_dom["editor_form"]) is not bool or
                any(type(upload_dom[key]) is not int or not 0 <= upload_dom[key] <= 10000 for key in upload_counts)):
            raise ValueError("invalid upload DOM diagnostic")
        with self.lock:
            if self.client is None:
                self.pair(client_id, account, visible_model, input_protocol)
            else:
                self._client(client_id)
            self.client.update(visible_model=visible_model, tab_ready=tab_ready, input_protocol=input_protocol,
                               tab_idle=tab_idle, tab_error=tab_error, worker_version=worker_version,
                               content_receiver=content_receiver, receiver_error=receiver_error,
                               upload_dom=dict(upload_dom) if upload_dom is not None else None)
            return self.status()

    def _client(self, client_id):
        if not isinstance(client_id, str) or not self.client or not hmac.compare_digest(self.client["client_id"], client_id):
            raise ValueError("extension is not paired")
        self.client["seen"] = time.monotonic()

    def submit(self, prompt: str, expected_model: str, mode: str = "create", images=None,
               preflight_only: bool = False, clear_preflight_uploads: bool = False) -> dict:
        if type(preflight_only) is not bool:
            raise ValueError("preflight_only must be a boolean")
        if type(clear_preflight_uploads) is not bool or (clear_preflight_uploads and not preflight_only):
            raise ValueError("clear_preflight_uploads requires a boolean and preflight_only=true")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 16000:
            raise ValueError("prompt must contain 1..16000 characters")
        if expected_model != "Create image":
            raise ValueError('expected_model must be exactly "Create image"')
        with self.lock:
            if not self.client or time.monotonic() - self.client["seen"] > 90:
                raise ValueError("pair a logged-in ChatGPT tab and wait for its heartbeat first")
            if any(j["state"] not in TERMINAL or j.get("cleanup_status") in {"pending", "confirmation_required"} for j in self.jobs.values()):
                raise ValueError("one image job at a time; inspect existing job before resubmitting")
            inputs = validated_inputs(mode, images)
            if (inputs or mode == "edit") and self.client.get("input_protocol", 0) < 1:
                raise ValueError("reload the updated extension and paired tab before using local image inputs")
            if preflight_only and self.client.get("input_protocol", 0) < 2:
                raise ValueError("reload extension and paired tab for no-Send preflight support")
            if clear_preflight_uploads and self.client.get("input_protocol", 0) < 3:
                raise ValueError("protocol 3 is required to clear verified preflight uploads")
            job = {"job_id": uuid.uuid4().hex, "state": "queued", "prompt": prompt, "account": self.account,
                   "expected_model": expected_model.strip(), "client_id": self.client["client_id"], "mode": mode}
            if inputs:
                directory = self.root / job["job_id"]
                directory.mkdir(mode=0o700)
                for metadata, raw in inputs:
                    stem, suffix = metadata["name"].rsplit(".", 1)
                    metadata["name"] = f"{stem}-{job['job_id']}.{suffix}"
                    descriptor = os.open(directory / metadata["name"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(raw)
                job["images"] = [metadata for metadata, _raw in inputs]
            if preflight_only:
                job["preflight_only"] = True
            if clear_preflight_uploads:
                job["clear_preflight_uploads"] = True
            if self.auto_delete_saved_chats and not preflight_only:
                job["auto_delete_saved_chat"] = True
            self.jobs[job["job_id"]] = job
            self._save(job)
            return self.status(job["job_id"])

    def claim(self, client_id: str) -> dict:
        with self.lock:
            self._client(client_id)
            for job in self.jobs.values():
                if job["state"] == "queued" and job["client_id"] == client_id:
                    minimum_protocol = 4 if job.get("preflight_cleanup_only") else 3 if job.get("clear_preflight_uploads") else 2 if job.get("preflight_only") else 1 if job.get("images") or job.get("mode") == "edit" else 0
                    if self.client.get("input_protocol", 0) < minimum_protocol:
                        job.update(state="failed", error="Input protocol changed before delivery; nothing was delivered. Reload extension and paired tab.")
                        self._save(job)
                        raise ValueError(job["error"])
                    job["state"] = "claimed"
                    self._save(job)  # Persist BEFORE delivery. Never repeat on uncertain response.
                    claimed = {k: job[k] for k in ("job_id", "prompt", "expected_model", "mode", "preflight_only", "clear_preflight_uploads", "preflight_cleanup_only", "preflight_cleanup_resumed") if k in job}
                    if job.get("preflight_cleanup_only"):
                        names = job.get("native_upload_names", [image["name"] for image in job["images"]])
                        claimed["images"] = [{**metadata, "name": names[index]}
                                             for index, metadata in enumerate(job["images"])]
                        if job.get("failed_upload_cleanup"):
                            claimed.update(preflight_only=True, clear_preflight_uploads=True)
                        return claimed  # Existing uploads only: never deliver image bytes again.
                    if job.get("images"):
                        claimed["images"] = []
                        try:
                            for metadata in job["images"]:
                                raw = read_local_image(str(self.root / job["job_id"] / metadata["name"]))
                                if len(raw) != metadata["bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
                                    raise ValueError("input snapshot changed")
                                claimed["images"].append({**metadata, "data_base64": base64.b64encode(raw).decode("ascii")})
                        except (OSError, ValueError) as error:
                            job.update(state="failed", error="Input snapshot unavailable or changed; nothing was delivered.")
                            self._save(job)
                            raise ValueError(job["error"]) from error
                    return claimed
            return {}

    def result(self, client_id: str, job_id: str, *, image_base64: str | None = None,
               error: str | None = None, source: str = "rendered-image", cleanup_pending: bool = False,
               chat_path: str | None = None, preflight_ready: bool = False,
               preflight_uploads_cleared: bool = False) -> dict:
        if type(cleanup_pending) is not bool or type(preflight_ready) is not bool or type(preflight_uploads_cleared) is not bool:
            raise ValueError("invalid cleanup flag")
        if chat_path is not None and (not isinstance(chat_path, str) or not re.fullmatch(r"/c/[a-f0-9-]{36}", chat_path)):
            raise ValueError("invalid generated chat path")
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if not job or job["client_id"] != client_id or job["state"] != "claimed":
                raise ValueError("job is not claimed by this extension; result was not accepted")
            if preflight_uploads_cleared and not (job.get("clear_preflight_uploads") or job.get("failed_upload_cleanup")):
                raise ValueError("preflight upload clearing was not requested")
            if error is not None:
                job.update(state="failed", error=str(error)[:500])
            elif job.get("failed_upload_cleanup"):
                if not preflight_ready or not preflight_uploads_cleared or image_base64 or cleanup_pending or chat_path:
                    raise ValueError("failed-upload cleanup requires only an empty-composer no-Send receipt")
                job.update(state="failed", error=job["original_upload_error"], uploads_cleared=True,
                           submitted=False, generated=False, cleanup_status="not_requested",
                           draft_note="Inspected failed-job uploads removed; composer empty. Original image request was not completed.")
            elif job.get("preflight_only"):
                if not preflight_ready or image_base64 or cleanup_pending or chat_path:
                    raise ValueError("preflight accepts only a no-Send readiness receipt, never media or cleanup")
                if job.get("clear_preflight_uploads") and not preflight_uploads_cleared:
                    raise ValueError("verified preflight upload clearing receipt is required")
                job.update(state="complete", preflight_ready=True, submitted=False, generated=False,
                           cleanup_status="not_requested", draft_note="Owned upload-only draft remains unsent; inspect before further work.")
                if preflight_uploads_cleared:
                    job.update(preflight_uploads_cleared=True,
                               draft_note="Owned preflight uploads removed after readiness verification; composer empty.")
            else:
                if preflight_ready:
                    raise ValueError("readiness receipt cannot complete a generation job")
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
            if cleanup_status == "confirmation_required" and job.get("auto_delete_saved_chat") is True:
                job["cleanup_confirmation"] = "requested"
            if cleanup_status == "failed":
                job["cleanup_error"] = error[:500]
            self._save(job)
            return self.status(job_id)

    def status(self, job_id: str = "") -> dict:
        with self.lock:
            if not job_id:
                return {"account": self.account, "paired": bool(self.client),
                        "cleanup_policy": "automatic_saved_chats" if self.auto_delete_saved_chats else "per_job_confirmation",
                        "account_binding": "owner-confirmed, not independently verified",
                        "transport": "extension-native-ui",
                        "input_capabilities": {"modes": ["create", "edit"],
                                               "ordered_local_images": bool(self.client and self.client.get("input_protocol", 0) >= 1),
                                               "preflight_only": bool(self.client and self.client.get("input_protocol", 0) >= 2),
                                               "preflight_clear_uploads": bool(self.client and self.client.get("input_protocol", 0) >= 3),
                                               "failed_preflight_cleanup": bool(self.client and self.client.get("input_protocol", 0) >= 4),
                                               "formats": ["PNG", "JPEG", "WEBP"], "static_only": True,
                                               "max_total_bytes": MAX_INPUT_BYTES, "max_edge": 8192,
                                               "max_pixels": 40_000_000, "max_metadata_bytes": 48 * 1024,
                                               "native_upload_count_limit": "not live verified"},
                        "visible_model": self.client["visible_model"] if self.client else None,
                        "tab_ready": bool(self.client and self.client["tab_ready"]),
                        "tab_idle": self.client.get("tab_idle") if self.client else None,
                        "tab_error": self.client.get("tab_error", "") if self.client else "",
                        "extension_diagnostics": {
                            "worker_version": (self.client.get("worker_version") or None) if self.client else None,
                            "content_receiver": self.client.get("content_receiver", "unreported") if self.client else "unreported",
                            "content_protocol": self.client.get("input_protocol", 0) if self.client else 0,
                            "receiver_error": self.client.get("receiver_error", "") if self.client else "",
                            "upload_dom": self.client.get("upload_dom") if self.client else None},
                        "extension_online": bool(self.client and time.monotonic() - self.client["seen"] <= 90),
                        "jobs": [{k: j[k] for k in ("job_id", "state", "cleanup_status", "chat_path", "preflight_only", "clear_preflight_uploads") if k in j}
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

    def resolve(self, job_id: str, clear_preflight_uploads: bool = False,
                clear_failed_uploads: bool = False, native_upload_names: list[str] | None = None) -> dict:
        """Explicit operator action after inspecting the upstream conversation."""
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("unknown job")
            if type(clear_preflight_uploads) is not bool:
                raise ValueError("clear_preflight_uploads must be a boolean")
            if type(clear_failed_uploads) is not bool or (clear_failed_uploads and clear_preflight_uploads):
                raise ValueError("choose one boolean upload cleanup action")
            if native_upload_names is not None and not clear_failed_uploads:
                raise ValueError("native_upload_names requires inspected failed-upload cleanup")
            if clear_failed_uploads:
                job = self.jobs[job_id]
                if (job["state"] != "failed" or job.get("preflight_only") or job.get("failed_upload_cleanup") or
                        not job.get("images") or not job.get("error", "").startswith("Not submitted. Native uploads not verified ready;")):
                    raise ValueError("only an inspected unsent generation upload failure can be cleared once")
                if (not isinstance(native_upload_names, list) or len(native_upload_names) != len(job["images"]) or
                        any(not isinstance(name, str) or not re.fullmatch(
                            re.escape(image["name"].rsplit(".", 1)[0]) + r"(?:\([1-9][0-9]{0,5}\))?\." +
                            re.escape(image["name"].rsplit(".", 1)[1]), name)
                            for name, image in zip(native_upload_names, job["images"])) or
                        len(set(native_upload_names)) != len(native_upload_names)):
                    raise ValueError("inspected native filenames must exactly match the original ordered names or numeric duplicate suffixes")
                if (not self.client or time.monotonic() - self.client["seen"] > 90 or
                        self.client.get("input_protocol", 0) < 4 or self.client["client_id"] != job["client_id"]):
                    raise ValueError("original paired extension with protocol 4 is required")
                if any(j["state"] not in TERMINAL or j.get("cleanup_status") in {"pending", "confirmation_required"} for j in self.jobs.values()):
                    raise ValueError("finish existing work before failed-upload cleanup")
                if max(self.jobs, key=lambda key: (self.root / key / "state.json").stat().st_mtime_ns) != job_id:
                    raise ValueError("only the latest inspected upload failure may clear existing uploads")
                job.update(state="queued", preflight_cleanup_only=True, failed_upload_cleanup=True,
                           native_upload_names=list(native_upload_names), original_upload_error=job.pop("error"))
                self._save(job)
                return self.status(job_id)
            if clear_preflight_uploads:
                job = self.jobs[job_id]
                resume = (job.get("preflight_cleanup_only") is True and
                          not job.get("preflight_cleanup_resumed") and
                          job.get("original_preflight_error", "").startswith("Not submitted. Native uploads not verified ready;") and
                          job.get("error") == "Not submitted. Unexpected attachment controls in this job's composer; inspect the unsent draft")
                if (job["state"] != "failed" or not job.get("preflight_only") or
                        not job.get("clear_preflight_uploads") or not job.get("images") or
                        (not resume and (job.get("preflight_cleanup_only") or
                         not job.get("error", "").startswith("Not submitted. Native uploads not verified ready;")))):
                    raise ValueError("only an inspected upload-readiness failure can clear its original preflight uploads once")
                if (not self.client or time.monotonic() - self.client["seen"] > 90 or
                        self.client.get("input_protocol", 0) < 4 or self.client["client_id"] != job["client_id"]):
                    raise ValueError("original paired extension with protocol 4 is required")
                if any(j["state"] not in TERMINAL or j.get("cleanup_status") in {"pending", "confirmation_required"} for j in self.jobs.values()):
                    raise ValueError("finish existing work before preflight cleanup")
                latest = max(self.jobs, key=lambda key: (self.root / key / "state.json").stat().st_mtime_ns)
                if latest != job_id:
                    raise ValueError("only the latest inspected preflight may clear existing uploads")
                error = job.pop("error")
                job.update(state="queued", preflight_cleanup_only=True)
                if resume:
                    job.update(preflight_cleanup_resumed=True, previous_preflight_cleanup_error=error)
                else:
                    job["original_preflight_error"] = error
                self._save(job)
                return self.status(job_id)
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
                    result = queue.pair(data["client_id"], data["account"], data.get("visible_model", ""), data.get("input_protocol", 0))
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
                    result = queue.resolve(data["job_id"], data.get("clear_preflight_uploads", False),
                                           data.get("clear_failed_uploads", False), data.get("native_upload_names"))
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
        """Check account, cleanup_policy and saved image receipt. In automatic_saved_chats mode, wait for cleanup_status=deleted; do not ask per image or call confirm_delete. Otherwise confirmation_required needs exact-chat owner approval. Pending cleanup blocks new images. Failure never means regenerate or repeat deletion."""
        return queue.status(job_id)

    @server.tool()
    def extension_image(prompt: str, expected_model: str, mode: Literal["create", "edit"] = "create",
                        images: list[LocalImageInput] | None = None, preflight_only: bool = False,
                        clear_preflight_uploads: bool = False) -> dict:
        """Create/edit ONE image on second, or preflight_only=true to verify actual uploads WITHOUT text insertion, Send or generation. Preflight normally preserves the unsent draft. With explicit owner approval, clear_preflight_uploads=true removes ONLY this job's verified uploads after readiness, requiring preflight_clear_uploads capability (protocol 3). create accepts ordered references; edit requires >=1 source. Local static PNG/JPEG/WebP, 8 MiB combined, <=40MP/8192px, no URLs/symlinks. Preserve order/roles. Check status/tab_idle. No retries or model/account parity promises."""
        return queue.submit(prompt, expected_model, mode, images, preflight_only, clear_preflight_uploads)

    @server.tool()
    def extension_confirm_delete(job_id: str, owner_confirmed: bool = False) -> dict:
        """Legacy per-job confirmation only; not needed when cleanup_policy=automatic_saved_chats. Permanently delete only this saved-image chat after exact-chat owner approval. Pass owner_confirmed=true only after that approval. Single-use: poll status, never retry uncertain deletion."""
        return queue.confirm_delete(job_id, owner_confirmed)

    @server.tool()
    def extension_resolve(job_id: str, inspected_chatgpt: StrictBool = False, clear_preflight_uploads: StrictBool = False,
                          clear_failed_uploads: StrictBool = False, native_upload_names: list[str] | None = None) -> dict:
        """Release uncertain work ONLY after inspection. With owner approval, clear_preflight_uploads=true removes a failed preflight's uploads; one explicit resume handles the known async-removal failure. For a normal generation that failed upload readiness BEFORE Send, clear_failed_uploads=true requires all exact inspected native_upload_names (numeric duplicate suffixes allowed). That request remains failed after its attachments are cleared; never resend automatically. Protocol 4, same client/latest job only. No re-upload, text, Send, generation or chat deletion. Refuses changed drafts."""
        if inspected_chatgpt is not True:
            raise ValueError("inspect ChatGPT before resolving uncertain work")
        if clear_failed_uploads or native_upload_names is not None:
            return queue.resolve(job_id, clear_preflight_uploads, clear_failed_uploads, native_upload_names)
        return queue.resolve(job_id, clear_preflight_uploads)

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
    parser.add_argument("--auto-delete-saved-chats", action="store_true",
                        help="Owner opt-in: permanently delete only new Bridge-created image chats after validated local save, without per-image prompts")
    args = parser.parse_args()
    if args.connect and args.auto_delete_saved_chats:
        parser.error("automatic cleanup is an owner-worker policy; set it on the owning command, not --connect")
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
    queue = ExtensionQueue(root, args.account, auto_delete_saved_chats=args.auto_delete_saved_chats)
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
