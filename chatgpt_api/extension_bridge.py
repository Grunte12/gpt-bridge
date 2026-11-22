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
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictBool

MAX_IMAGE = 25 * 1024 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024  # Local transport budget, NOT a ChatGPT upload limit.
TERMINAL = {"complete", "failed", "interrupted"}
OPEN_CLEANUP = {"pending", "confirmation_required", "timeout_delete_pending", "timeout_delete_failed"}
MAX_WAITING_JOBS = 10  # Jobs line up first-in, first-out; a full line is refused, never dropped.
GENERATION_TIMEOUT_MIN = 600
GENERATION_TIMEOUT_MAX = 900
GENERATION_TIMEOUT_MULTIPLIER = 2.5
GENERATION_TIMEOUT_SAMPLES = 5
MAX_TIMEOUT_REPLACEMENTS = 1
AUTOMATION_PHASES = ("prepared", "submit_attempted", "remote_started", "result_captured", "completed")
AUTOMATION_PHASE_RANK = {phase: index for index, phase in enumerate(AUTOMATION_PHASES)}


_MANIFEST = Path(__file__).resolve().parent.parent / "extensions" / "chatgpt-image" / "manifest.json"
_manifest_cache: tuple[int, str | None] = (-1, None)


def repo_extension_version() -> str | None:
    """Version of the extension files on disk; Chrome keeps running the old one until it is reloaded.
    Cached by file mtime so status polling does not re-read the file."""
    global _manifest_cache
    try:
        stamp = _MANIFEST.stat().st_mtime_ns
        if _manifest_cache[0] != stamp:
            version = json.loads(_MANIFEST.read_text(encoding="utf-8")).get("version")
            _manifest_cache = (stamp, version if isinstance(version, str) else None)
        return _manifest_cache[1]
    except (OSError, ValueError):
        return None


def job_occupies_tab(job: dict) -> bool:
    return job.get("state") not in TERMINAL or job.get("cleanup_status") in OPEN_CLEANUP


def job_holds_tab(job: dict) -> bool:
    """Running or cleaning up. A job still waiting in line has not touched the tab yet."""
    return job_occupies_tab(job) and job.get("state") not in {"queued", "waiting_for_batch"}


def ended_uncertain(job: dict) -> bool:
    """A failed or interrupted job that may already have reached ChatGPT: a human must inspect it before the line moves on.
    Only jobs that were actually delivered count. A worker without phase receipts (old extension) can never prove 'not sent'."""
    if job.get("state") not in {"failed", "interrupted"} or not job.get("delivered") or job.get("inspected"):
        return False
    if job.get("preflight_only") or job.get("preflight_cleanup_only") or job.get("collect_only"):
        return False
    return not job.get("phase_capable") or job.get("phase", "prepared") != "prepared"


def short_outputs(raw: dict) -> list | None:
    outputs = raw.get("outputs")
    if not isinstance(outputs, list) or len(outputs) < 2:
        return None
    fields = ("order", "image_path", "dimensions", "sha256", "bytes")
    if any(not isinstance(item, dict) for item in outputs):
        return None
    return [{key: item.get(key) for key in fields} for item in outputs]
PORT = 18767
# A diagnostic-only reload must not unlock another collection attempt.
OUTPUT_BINDING_REVISIONS = {"0.1.20": 0, "0.1.21": 1, "0.1.22": 1, "0.1.23": 2, "0.1.24": 2, "0.1.25": 2, "0.1.26": 2, "0.1.27": 2, "0.1.28": 2, "0.1.29": 2, "0.1.30": 2, "0.1.31": 2, "0.1.32": 2, "0.1.33": 2, "0.1.34": 2, "0.1.35": 2, "0.1.36": 2, "0.1.37": 2, "0.1.38": 2, "0.1.39": 2, "0.1.45": 2, "0.1.46": 2}
TAB_RECOVERY = {"none", "rebound", "unmatched"}
TIMEOUT_REASONS = {"", "no_image_returned", "still_generating", "page_hidden_unverified"}


def timeout_delete_failed(job: dict) -> bool:
    """The stalled chat could not be deleted. It is kept ("preserved") and never blocks the line."""
    return job.get("cleanup_status") == "timeout_delete_failed" or (
        job.get("cleanup_status") == "preserved" and job.get("previous_cleanup_status") == "timeout_delete_failed")
_PREPARE_BLOCKERS = {
    "ChatGPT composer unavailable. Nothing was submitted.": ("composer_unavailable", "inspect_paired_composer",
        "Queued, not sent. Check that the paired ChatGPT tab shows the message box. The same request resumes when ready; do not resubmit."),
    "Remove existing attachments before using the image worker": ("existing_attachments", "preserve_paired_attachments",
        "Your order is accepted and queued, not sent. No action is needed from you. An existing draft in the paired ChatGPT tab has an attachment. Do not remove or move it; leave that draft untouched. When its owner finishes normally, this same order continues automatically."),
    "Preserve the draft or running work. Nothing was submitted.": ("draft_or_busy", "wait_for_clean_composer",
        "Queued, not sent. Leave the existing draft or generation alone. The same request resumes when the paired composer is free."),
}


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

    def call(self, action: str, data: dict, timeout: float = 10) -> dict:
        request = Request(f"http://127.0.0.1:{PORT}/agent/{action}",
                          data=json.dumps(data).encode(), method="POST",
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"})
        try:
            with self.http.open(request, timeout=timeout) as response:
                raw = response.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                raise ValueError("oversized worker response")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("invalid worker response")
            return result
        except HTTPError as from_error:
            detail = ""
            try:
                parsed = json.loads(from_error.read(4096))
                if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
                    detail = parsed["error"][:300]
            except (OSError, ValueError, TypeError, AttributeError):
                detail = ""
            if detail:
                raise ValueError(detail) from from_error
            raise ValueError("Local extension worker unavailable or request rejected; inspect status before retrying. No automatic retry.") from from_error
        except (URLError, OSError, ValueError) as from_error:
            raise ValueError("Local extension worker unavailable or request rejected; inspect status before retrying. No automatic retry.") from from_error

    def status(self, job_id: str = "") -> dict:
        return self.call("status", {"job_id": job_id})

    def wait_for_job(self, job_id: str, timeout_seconds: int = 120) -> dict:
        return self.call("wait", {"job_id": job_id, "timeout_seconds": timeout_seconds}, timeout=timeout_seconds + 15)

    def submit(self, prompt: str, expected_model: str, mode: str = "create", images=None,
               preflight_only: bool = False, clear_preflight_uploads: bool = False) -> dict:
        return self.call("image", {"prompt": prompt, "expected_model": expected_model, "mode": mode,
                                   "images": [item.model_dump() if isinstance(item, LocalImageInput) else item
                                              for item in (images or [])], "preflight_only": preflight_only,
                                   **({"clear_preflight_uploads": clear_preflight_uploads} if clear_preflight_uploads is not False else {})})

    def resolve(self, job_id: str, clear_preflight_uploads: bool = False,
                clear_failed_uploads: bool = False, native_upload_names: list[str] | None = None,
                recover_outputs: bool = False, recovery_chat_path: str | None = None,
                inspected_chatgpt: bool = True) -> dict:
        if inspected_chatgpt is not True:
            raise ValueError("inspect ChatGPT before resolving uncertain work")
        return self.call("resolve", {"job_id": job_id, "inspected_chatgpt": True,
                                    **({"clear_preflight_uploads": clear_preflight_uploads} if clear_preflight_uploads is not False else {}),
                                    **({"clear_failed_uploads": clear_failed_uploads} if clear_failed_uploads is not False else {}),
                                    **({"native_upload_names": native_upload_names} if native_upload_names is not None else {}),
                                    **({"recover_outputs": True} if recover_outputs else {}),
                                    **({"recovery_chat_path": recovery_chat_path} if recovery_chat_path is not None else {})})

    def batch_start(self, batch_id: str, items: list, destination: str, attempts: str) -> dict:
        return self.call("batch-start", {"batch_id": batch_id, "items": items, "destination": destination, "attempts": attempts})

    def batch_status(self, batch_id: str) -> dict:
        return self.call("batch-status", {"batch_id": batch_id})

    def enqueue(self, request_id: str, prompt: str, images=None, mode: str = "create", cleanup: str | None = None) -> dict:
        return self.call("enqueue", {"request_id": request_id, "prompt": prompt, "mode": mode,
                                    "images": [item.model_dump() if isinstance(item, LocalImageInput) else item
                                               for item in (images or [])],
                                    **({"cleanup": cleanup} if cleanup is not None else {})})

    def confirm_delete(self, job_id: str, owner_confirmed: bool = False) -> dict:
        return self.call("confirm-delete", {"job_id": job_id, "owner_confirmed": owner_confirmed})


class ExtensionQueue:
    def __init__(self, root: Path, account: str, *, auto_delete_saved_chats: bool = False, batch_allowed_runs=()):
        if type(auto_delete_saved_chats) is not bool:
            raise ValueError("invalid chat cleanup policy")
        if root.is_symlink():
            raise ValueError("data directory must not be a symlink")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.account = account
        from .extension_batch import real_directory
        self.batch_allowed_runs = frozenset(real_directory(str(p)) for p in batch_allowed_runs)
        self.auto_delete_saved_chats = auto_delete_saved_chats
        self.lock = threading.RLock()
        self.finished = threading.Condition(self.lock)
        self.client = None
        self.reload_requested = False  # One-shot: the next idle heartbeat tells the worker to reload itself.
        self.halted_job: str | None = None  # Line stops here until the owner inspects ChatGPT and calls resolve.
        self._batch = None
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
            if (record.get("request_id") and record.get("state") in {"queued", "waiting_for_batch"}
                    and record.get("phase") == "prepared" and not record.get("delivered")):
                continue  # Accepted, never-delivered requests retain their pinned payload across restart.
            if record.get("state") not in TERMINAL:
                stalled_age = time.time() - path.stat().st_mtime
                legacy_stalled = (record.get("state") == "claimed" and record.get("phase") == "remote_started" and
                                  re.fullmatch(r"/c/[a-f0-9-]{36}", record.get("chat_path", "")) and
                                  stalled_age >= GENERATION_TIMEOUT_MAX and not record.get("images") and
                                  record.get("mode", "create") == "create" and not record.get("batch_id") and record.get("retry_count", 0) < MAX_TIMEOUT_REPLACEMENTS)
                if legacy_stalled:
                    replacement = {"job_id": uuid.uuid4().hex, "state": "queued", "phase": "prepared",
                                   "prompt": record["prompt"], "account": self.account, "created_at": time.time(),
                                   "expected_model": record["expected_model"], "client_id": record["client_id"], "mode": "create",
                                   "retry_count": record.get("retry_count", 0) + 1,
                                   "replaces_job_id": record["job_id"], "generation_baseline_seconds": 120.0,
                                   "generation_timeout_seconds": GENERATION_TIMEOUT_MIN, "generation_timing_samples": 0,
                                   **({"auto_delete_saved_chat": True} if self.auto_delete_saved_chats else {})}
                    record.update(state="failed", timed_out=True, inspected=True, submitted=True, generated=False,
                                  completed_at=time.time(), cleanup_status="timeout_delete_pending",
                                  replacement_job_id=replacement["job_id"],
                                  error="Legacy generation exceeded 900s; deleting the exact stalled chat before replacement.")
                    self._save(record)
                    self.jobs[replacement["job_id"]] = replacement
                    self._save(replacement)
                else:
                    never_sent = record.get("state") == "queued" or (
                        record.get("delivered") and record.get("phase_capable") and record.get("phase", "prepared") == "prepared")
                    record.update(state="interrupted", error=(
                        "Server restarted before this job was sent; nothing reached ChatGPT. Submit it again." if never_sent
                        else "Server restarted. Check the original ChatGPT conversation. No automatic retry; do not submit a second job."))
                    self._save(record)
            elif record.get("cleanup_status") == "timeout_delete_failed":
                record.update(cleanup_status="preserved", previous_cleanup_status="timeout_delete_failed", delete_failed=True)
                self._save(record)
            elif record.get("cleanup_status") in {"pending", "confirmation_required"}:
                record.update(cleanup_status="failed", cleanup_confirmation="invalidated",
                              cleanup_error="Server restarted before cleanup was verified; inspect the chat, do not repeat deletion automatically.")
                self._save(record)

        if (self.root / "batches").is_dir():
            from .extension_batch import BatchFeeder
            self._batch = BatchFeeder(self)

    def _save(self, job):
        directory = self.root / job["job_id"]
        directory.mkdir(mode=0o700, exist_ok=True)
        from .extension_batch import atomic_json
        atomic_json(directory / "state.json", job)
        if ended_uncertain(job) and self.halted_job is None:
            self.halted_job = job["job_id"]
        with self.finished:
            self.finished.notify_all()

    def pair(self, client_id: str, account: str | None = None, visible_model: str = "", input_protocol: int = 0,
             tab_id: int | None = None, retry_timeout_cleanup: bool = False, automatic: bool = False) -> dict:
        # Old clients sent a local queue namespace, never a verified ChatGPT identity.
        if (account is not None and account != self.account) or not isinstance(client_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", client_id):
            raise ValueError("legacy namespace or client identity mismatch")
        if not isinstance(visible_model, str) or len(visible_model) > 100:
            raise ValueError("invalid visible model label")
        if type(input_protocol) is not int or input_protocol not in {0, 1, 2, 3, 4}:
            raise ValueError("invalid input protocol")
        if tab_id is not None and (type(tab_id) is not int or tab_id < 0):
            raise ValueError("invalid paired tab identity")
        if type(retry_timeout_cleanup) is not bool:
            raise ValueError("retry_timeout_cleanup must be a boolean")
        if type(automatic) is not bool:
            raise ValueError("automatic must be a boolean")
        with self.lock:
            if automatic and self.client and self.client["client_id"] != client_id:
                raise ValueError("another Chrome profile owns this worker; keep its pairing or explicitly reconnect")
            resumable = lambda job: (job.get("request_id") and job.get("state") in {"queued", "waiting_for_batch"}
                                     and job.get("phase") == "prepared" and not job.get("delivered")
                                     and job.get("client_id") == client_id)
            if automatic and (self.halted_job or any(job_occupies_tab(job) and not resumable(job) for job in self.jobs.values())):
                raise ValueError("existing work requires its original paired tab; automatic pairing refused")
            open_jobs = [job for job in self.jobs.values() if job_occupies_tab(job) and not resumable(job)]
            # A queued replacement could run after cleanup; keep it outside recovery.
            if len(open_jobs) > 1:
                raise ValueError("finish the current job before pairing again; call wait and do not send again")
            if retry_timeout_cleanup:
                cleanup_job = next((job for job in open_jobs if job.get("cleanup_status") == "timeout_delete_failed"), None)
                if cleanup_job is None:
                    raise ValueError("no failed timeout cleanup is available for explicit retry")
            else:
                cleanup_job = next((job for job in open_jobs if job.get("cleanup_status") == "timeout_delete_pending"), None)
                if cleanup_job is None and any(job.get("cleanup_status") == "timeout_delete_failed" for job in open_jobs):
                    raise ValueError("timeout cleanup failed; explicitly retry that cleanup before pairing")
            if open_jobs and cleanup_job is None:
                raise ValueError("finish the current job before pairing again; call wait and do not send again")
            if cleanup_job is not None:
                replacements = [job for job in open_jobs if job is not cleanup_job]
                replacement_id = cleanup_job.get("replacement_job_id")
                valid_replacement = (len(replacements) == 1 and replacements[0].get("job_id") == replacement_id and
                                     replacements[0].get("replaces_job_id") == cleanup_job.get("job_id") and
                                     replacements[0].get("state") == "queued" and
                                     replacements[0].get("phase") == "prepared" and
                                     replacements[0].get("delivered") is not True and
                                     replacements[0].get("account") == self.account and
                                     replacements[0].get("mode") == "create" and
                                     replacements[0].get("prompt") == cleanup_job.get("prompt") and
                                     replacements[0].get("expected_model") == cleanup_job.get("expected_model"))
                failed_cleanup = cleanup_job.get("cleanup_status") == "timeout_delete_failed"
                if (len(replacements) > 1 or (replacements and not valid_replacement) or
                        cleanup_job.get("state") != "failed" or
                        cleanup_job.get("timed_out") is not True or cleanup_job.get("phase") != "remote_started" or
                        cleanup_job.get("submitted") is not True or cleanup_job.get("generated") is not False or
                        not re.fullmatch(r"/c/[a-f0-9-]{36}", cleanup_job.get("chat_path", ""))):
                    raise ValueError("timeout cleanup is not safe to resume; inspect MCP status")
                if failed_cleanup:
                    retry_count = cleanup_job.get("cleanup_retry_count", 0)
                    error_history = cleanup_job.get("cleanup_error_history", [])
                    previous_error = cleanup_job.get("cleanup_error")
                    if (type(retry_count) is not int or retry_count < 0 or not isinstance(error_history, list) or
                            any(not isinstance(item, str) for item in error_history) or
                            (previous_error is not None and not isinstance(previous_error, str))):
                        raise ValueError("timeout cleanup retry history is invalid; inspect MCP status")
                if (self.client and time.monotonic() - self.client.get("seen", 0) <= 90 and
                        self.client.get("client_id") != client_id):
                    raise ValueError("original extension must be offline before cleanup recovery")
                if failed_cleanup:
                    previous_error = cleanup_job.get("cleanup_error")
                    if previous_error:
                        cleanup_job.setdefault("cleanup_error_history", []).append(previous_error[:500])
                    cleanup_job["cleanup_retry_count"] = cleanup_job.get("cleanup_retry_count", 0) + 1
                    cleanup_job["cleanup_status"] = "timeout_delete_pending"
                    cleanup_job.pop("cleanup_error", None)
                cleanup_job["client_id"] = client_id
                self._save(cleanup_job)
                if replacements:
                    replacements[0]["client_id"] = client_id
                    self._save(replacements[0])
            self.client = {"client_id": client_id, "seen": time.monotonic(), "visible_model": visible_model,
                           "tab_ready": True, "input_protocol": input_protocol, "tab_id": tab_id}
            for pending in self.jobs.values():
                if resumable(pending):
                    pending["client_id"] = client_id
                    self._save(pending)
            result = {"paired": True, "account_source": "chrome_login", "identity": "uses the login in the paired Chrome tab"}
            if cleanup_job is not None:
                result.update(cleanup_pending=True, timeout_cleanup_job={key: cleanup_job[key] for key in
                    ("job_id", "prompt", "expected_model", "mode", "chat_path") if key in cleanup_job})
            return result

    def heartbeat(self, client_id: str, account: str | None = None, visible_model: str = "Create image",
                  tab_ready: bool = False, input_protocol: int = 0,
                  tab_idle: bool | None = None, tab_error: str = "",
                  worker_version: str = "", content_receiver: str = "unreported",
                  receiver_error: str = "", upload_dom: dict | None = None, result_dom: dict | None = None,
                  prompt_dom: dict | None = None, tab_recovery: str = "none", chatgpt_tabs: int = 0,
                  tab_id: int | None = None) -> dict:
        """Reconnect the already-authorized local extension, never replay old work."""
        if (account is not None and account != self.account) or type(tab_ready) is not bool:
            raise ValueError("legacy namespace or readiness mismatch")
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
        if not isinstance(tab_recovery, str) or tab_recovery not in TAB_RECOVERY:
            raise ValueError("invalid tab recovery diagnostic")
        if type(chatgpt_tabs) is not int or not 0 <= chatgpt_tabs <= 20:
            raise ValueError("invalid ChatGPT tab count")
        if tab_id is not None and (type(tab_id) is not int or tab_id < 0):
            raise ValueError("invalid paired tab identity")
        upload_counts = {"file_inputs", "form_file_inputs", "image_inputs", "form_image_inputs",
                         "multiple_image_inputs", "unrestricted_inputs", "attachment_cards"}
        if upload_dom is not None and (not isinstance(upload_dom, dict) or
                set(upload_dom) != upload_counts | {"editor_form"} or type(upload_dom["editor_form"]) is not bool or
                any(type(upload_dom[key]) is not int or not 0 <= upload_dom[key] <= 10000 for key in upload_counts)):
            raise ValueError("invalid upload DOM diagnostic")
        result_counts = {"assistant_role_nodes", "user_headings", "assistant_headings", "assistant_images", "conversation_images"}
        if result_dom is not None and (not isinstance(result_dom, dict) or
                set(result_dom) != result_counts | {"assistant_body_found", "busy", "chat_path"} or
                any(type(result_dom[key]) is not int or not 0 <= result_dom[key] <= 10000 for key in result_counts) or
                any(type(result_dom[key]) is not bool for key in ("assistant_body_found", "busy")) or
                not isinstance(result_dom["chat_path"], str) or
                (result_dom["chat_path"] != "" and not re.fullmatch(r"/c/[a-f0-9-]{36}", result_dom["chat_path"]))):
            raise ValueError("invalid result DOM diagnostic")
        if prompt_dom is not None:
            counts = {"body_chars", "stripped_chars", "matched_chip_chars", "label_count"}
            flags = {"starts_with_label", "ends_with_label"}
            label_flags = {"inline_pill", "system_hint", "prompt_link", "in_button", "matched_chip"}
            tags = {"DIV", "SPAN", "BUTTON", "A", "P", "OTHER"}
            if (not isinstance(prompt_dom, dict) or set(prompt_dom) != counts | flags | {"labels"} or
                    any(type(prompt_dom[key]) is not int or not 0 <= prompt_dom[key] <=
                        (10000 if key == "label_count" else 100000) for key in counts) or
                    any(type(prompt_dom[key]) is not bool for key in flags) or
                    not isinstance(prompt_dom["labels"], list) or
                    len(prompt_dom["labels"]) != min(prompt_dom["label_count"], 8) or
                    any(not isinstance(label, dict) or set(label) != label_flags | {"tag", "parent_tag"} or
                        not isinstance(label["tag"], str) or label["tag"] not in tags or
                        not isinstance(label["parent_tag"], str) or label["parent_tag"] not in tags or
                        any(type(label[key]) is not bool for key in label_flags) for label in prompt_dom["labels"])):
                raise ValueError("invalid bounded prompt DOM diagnostic")
        with self.lock:
            prior_blocker = self._prepare_blocker()
            if self.client is None:
                # Rebind the original worker only to inspect a completed timed-out chat;
                # the queue remains blocked until explicit collect-only recovery.
                open_jobs = [j for j in self.jobs.values() if job_occupies_tab(j)]
                stale = open_jobs[0] if len(open_jobs) == 1 else None
                safe_inspection = (stale and stale.get("state") == "failed" and
                    stale.get("timed_out") is True and stale.get("cleanup_status") == "timeout_delete_failed" and
                    stale.get("phase") == "remote_started" and stale.get("submitted") is True and
                    not stale.get("replacement_job_id") and stale.get("client_id") == client_id and
                    stale.get("browser_tab_id") == tab_id and tab_id is not None and
                    worker_version in OUTPUT_BINDING_REVISIONS and isinstance(result_dom, dict) and
                    result_dom.get("chat_path") == stale.get("chat_path") and
                    result_dom.get("assistant_body_found") and not result_dom.get("busy") and
                    1 <= result_dom.get("assistant_images", 0) <= 4 and
                    result_dom.get("user_headings") == 1 and result_dom.get("assistant_headings") == 1)
                if safe_inspection:
                    self.client = {"client_id": client_id, "seen": time.monotonic(),
                                   "visible_model": visible_model, "tab_ready": tab_ready,
                                   "input_protocol": input_protocol, "tab_id": tab_id}
                else:
                    self.pair(client_id, account, visible_model, input_protocol, tab_id)
            else:
                self._client(client_id)
                if self.client.get("tab_id") is not None and tab_id != self.client["tab_id"]:
                    if any(job_holds_tab(job) for job in self.jobs.values()):
                        raise ValueError("paired tab identity changed during work; inspect the original job, never replay")
                    self.client["tab_id"] = tab_id  # Worker already proved the persistent client marker on this tab.
            self.client.update(visible_model=visible_model, tab_ready=tab_ready, input_protocol=input_protocol,
                               tab_idle=tab_idle, tab_error=tab_error, worker_version=worker_version,
                               content_receiver=content_receiver, receiver_error=receiver_error,
                               tab_recovery=tab_recovery, chatgpt_tabs=chatgpt_tabs,
                               tab_id=tab_id,
                               upload_dom=dict(upload_dom) if upload_dom is not None else None,
                               result_dom=dict(result_dom) if result_dom is not None else None,
                               prompt_dom=json.loads(json.dumps(prompt_dom)) if prompt_dom is not None else None)
            if self._prepare_blocker() != prior_blocker:
                self.finished.notify_all()
            reply = self.status()
            # Delivered once. A heartbeat sent while a result is being saved reports "unreported" and its reply is ignored.
            if reply["next_action"] == "reload_extension" and content_receiver != "unreported":
                self.reload_requested = False
            return reply

    def request_reload(self) -> dict:
        """Ask the worker to reload the extension at its next idle heartbeat. Never touches jobs."""
        with self.lock:
            action = self._next_action()
            if action in {"wait_for_extension", "inspect_halted_job"}:
                raise ValueError(f"reload not requested: next_action is {action}")
            self.reload_requested = True
            return {"reload_requested": True, "next_action": self._next_action()}

    def _prepare_blocker(self, job=None):
        client = self.client or {}
        if (client.get("content_receiver") != "available" or client.get("tab_ready")
                or (job and (job.get("preflight_cleanup_only") or job.get("collect_only")))):
            return None
        return _PREPARE_BLOCKERS.get(client.get("tab_error"))

    def _waiting(self):
        return sorted((j for j in self.jobs.values() if j["state"] in {"queued", "waiting_for_batch"}),
                      key=lambda j: (j.get("queue_sequence", 0), j.get("created_at", 0), j["job_id"]))

    def _next_action(self) -> str:
        """One machine-readable next step. Never includes page content or a tab URL."""
        running = self.client.get("worker_version") if self.client else None
        installed = repo_extension_version()
        if (running and installed and running != installed and
                any(job.get("cleanup_status") == "timeout_delete_pending" for job in self.jobs.values())):
            return "reload_extension"
        if any(job_holds_tab(job) for job in self.jobs.values()):
            return "wait"
        if self.halted_job:
            return "inspect_halted_job"  # Owner inspects ChatGPT, then resolve(job_id) lets the line continue.
        if not self.client or time.monotonic() - self.client.get("seen", 0) > 90:
            return "wait_for_extension"
        running, installed = self.client.get("worker_version"), repo_extension_version()
        if self.reload_requested or (running and installed and running != installed):
            return "reload_extension"  # Chrome still runs the old files (or a reload was requested): the worker reloads when idle.
        tabs = self.client.get("chatgpt_tabs", 0)
        recovery = self.client.get("tab_recovery", "none")
        receiver = self.client.get("content_receiver", "unreported")
        if (self.client.get("tab_error") or "").startswith("Owner action required"):
            return "verify_paired_tab"
        if recovery == "unmatched" or receiver == "wrong_origin" or (receiver == "tab_missing" and tabs > 0):
            return "confirm_paired_tab"
        if receiver == "tab_missing":
            return "open_chatgpt_tab"
        if receiver == "unavailable" and self.client.get("receiver_error") == "no_receiver":
            return "refresh_paired_tab_once"
        if blocker := self._prepare_blocker():
            head = next((j for j in self._waiting() if j["state"] == "queued"
                         and j.get("client_id") == self.client["client_id"]), None)
            if head is None or self._prepare_blocker(head):
                return blocker[1]
        if any(job_occupies_tab(job) for job in self.jobs.values()):
            return "wait"  # Jobs are lined up; more can be added.
        if self.client.get("tab_ready") is True or self.client.get("content_receiver") == "available":
            return "submit_via_mcp"
        return "wait_for_tab"

    def _client(self, client_id):
        if not isinstance(client_id, str) or not self.client or not hmac.compare_digest(self.client["client_id"], client_id):
            raise ValueError("extension is not paired")
        self.client["seen"] = time.monotonic()

    def _generation_timing(self) -> dict:
        durations = []
        for job_id, job in reversed(list(self.jobs.items())):
            if job.get("state") != "complete" or job.get("generated") is not True:
                continue
            started, completed = job.get("remote_started_at"), job.get("completed_at")
            duration = completed - started if isinstance(started, (int, float)) and isinstance(completed, (int, float)) else None
            if duration is None:
                try:
                    directory = self.root / job_id
                    state_path = directory / "state.json"
                    created = getattr(directory.stat(), "st_birthtime", directory.stat().st_ctime)
                    duration = state_path.stat().st_mtime - created
                except OSError:
                    continue
            if 30 <= duration <= GENERATION_TIMEOUT_MAX:
                durations.append(float(duration))
            if len(durations) == GENERATION_TIMEOUT_SAMPLES:
                break
        average = sum(durations) / len(durations) if durations else GENERATION_TIMEOUT_MIN / GENERATION_TIMEOUT_MULTIPLIER
        timeout = max(GENERATION_TIMEOUT_MIN, min(GENERATION_TIMEOUT_MAX, int((average * GENERATION_TIMEOUT_MULTIPLIER + 14) // 15 * 15)))
        return {"generation_baseline_seconds": round(average, 1),
                "generation_timeout_seconds": timeout,
                "generation_timing_samples": len(durations)}

    def submit(self, prompt: str, expected_model: str, mode: str = "create", images=None,
               preflight_only: bool = False, clear_preflight_uploads: bool = False, *,
               _batch_job_id: str = "", _batch_id: str = "", _request_id: str = "", _cleanup: str | None = None) -> dict:
        if _cleanup not in {None, "delete_on_success", "keep"}:
            raise ValueError("cleanup must be delete_on_success or keep")
        if type(preflight_only) is not bool:
            raise ValueError("preflight_only must be a boolean")
        if type(clear_preflight_uploads) is not bool or (clear_preflight_uploads and not preflight_only):
            raise ValueError("clear_preflight_uploads requires a boolean and preflight_only=true")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 16000:
            raise ValueError("prompt must contain 1..16000 characters")
        if expected_model != "Create image":
            raise ValueError('expected_model must be exactly "Create image"')
        with self.lock:
            fingerprint = None
            if _request_id:
                if not isinstance(_request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", _request_id):
                    raise ValueError("request_id must contain 1..100 letters, digits, hyphens or underscores")
                normalized = [item if isinstance(item, LocalImageInput) else LocalImageInput.model_validate(item)
                              for item in (images or [])]
                fingerprint = hashlib.sha256(json.dumps({"prompt": prompt, "mode": mode,
                    "images": [item.model_dump() for item in normalized]}, sort_keys=True).encode()).hexdigest()
                previous = next((j for j in self.jobs.values() if j.get("request_id") == _request_id), None)
                if previous:
                    if previous.get("request_fingerprint") != fingerprint:
                        raise ValueError("request_id already accepted with a different payload")
                    return self.status(previous["job_id"])  # Reuse accepted bytes, not mutable source files.
            active = next((b for b in self._batch.batches.values() if b["state"] == "running"), None) if self._batch else None
            if active and not _batch_id and not _request_id:
                raise ValueError("a batch owns the image queue: " + active["batch_id"] + "; use enqueue with a stable request_id")
            if not self.client or time.monotonic() - self.client["seen"] > 90:
                raise ValueError("pair a logged-in ChatGPT tab and wait for its heartbeat first")
            if any(job.get("timed_out") is True and job.get("cleanup_status") in
                   {"timeout_delete_pending", "timeout_delete_failed"} for job in self.jobs.values()):
                raise ValueError("finish timeout cleanup for the exact stalled chat before creating another image")
            open_jobs = [job for job in self.jobs.values() if job_occupies_tab(job)
                         and not (_batch_id and job.get("state") == "waiting_for_batch")]
            if len(open_jobs) >= MAX_WAITING_JOBS:
                raise ValueError(f"image queue is full ({MAX_WAITING_JOBS} jobs); call wait for {open_jobs[0]['job_id']}. Do not resolve or send again.")
            running, installed = self.client.get("worker_version"), repo_extension_version()
            if installed and running and running != installed:
                raise ValueError(f"reload the extension (running {running}, installed {installed}) before sending; old workers cannot prove what was sent")
            inputs = validated_inputs(mode, images)
            if (inputs or mode == "edit") and self.client.get("input_protocol", 0) < 1:
                raise ValueError("reload the updated extension and paired tab before using local image inputs")
            if preflight_only and self.client.get("input_protocol", 0) < 2:
                raise ValueError("reload extension and paired tab for no-Send preflight support")
            if clear_preflight_uploads and self.client.get("input_protocol", 0) < 3:
                raise ValueError("protocol 3 is required to clear verified preflight uploads")
            job = {"job_id": _batch_job_id or uuid.uuid4().hex, "state": "queued", "phase": "prepared",
                   "prompt": prompt, "account": self.account, "created_at": time.time(),
                   "queue_sequence": 1 + max((j.get("queue_sequence", 0) for j in self.jobs.values()), default=0),
                   "expected_model": expected_model.strip(), "client_id": self.client["client_id"], "mode": mode,
                   "retry_count": 0, **self._generation_timing()}
            if _request_id:
                job.update(request_id=_request_id, request_fingerprint=fingerprint,
                           accepted_sequence=1 + max((j.get("accepted_sequence", 0) for j in self.jobs.values()), default=0),
                           payload_hash=hashlib.sha256(json.dumps({"prompt": prompt, "mode": mode,
                               "images": [{k: m[k] for k in ("role", "description", "sha256")} for m, _ in inputs]},
                               sort_keys=True).encode()).hexdigest())
                if active:
                    job.update(state="waiting_for_batch", blocked_by_batch=active["batch_id"])
            if inputs:
                directory = self.root / job["job_id"]
                directory.mkdir(mode=0o700)
                for metadata, raw in inputs:
                    stem, suffix = metadata["name"].rsplit(".", 1)
                    metadata["name"] = f"{stem}-{job['job_id']}.{suffix}"
                    from .extension_batch import durable_write
                    durable_write(directory / metadata["name"], raw, exclusive=True)
                job["images"] = [metadata for metadata, _raw in inputs]
            if preflight_only:
                job["preflight_only"] = True
            if clear_preflight_uploads:
                job["clear_preflight_uploads"] = True
            if _batch_id:
                if not re.fullmatch(r"[a-f0-9]{32}", _batch_job_id) or _batch_job_id in self.jobs:
                    raise ValueError("invalid or duplicate batch job identity")
                job["batch_id"] = _batch_id
            # run() states its cleanup per request; other callers follow the owner's worker policy.
            if not preflight_only and (_cleanup == "delete_on_success" or (_cleanup is None and self.auto_delete_saved_chats)):
                job["auto_delete_saved_chat"] = True
            if _cleanup:
                job["cleanup_requested"] = _cleanup
            self._save(job)
            self.jobs[job["job_id"]] = job
            return self.status(job["job_id"])

    def enqueue(self, request_id: str, prompt: str, images=None, mode: str = "create", cleanup: str | None = None) -> dict:
        """Accept once, pin inputs, and wait behind the current immutable batch without interleaving."""
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("a stable request_id is required")
        return self.submit(prompt, "Create image", mode, images, _request_id=request_id, _cleanup=cleanup)

    def batch_start(self, batch_id: str, items: list, destination: str, attempts: str) -> dict:
        with self.lock:
            if self._batch is None:
                from .extension_batch import BatchFeeder
                self._batch = BatchFeeder(self)
            return self._batch.start(batch_id, items, destination, attempts)

    def batch_status(self, batch_id: str) -> dict:
        with self.lock:
            if self._batch is None:
                from .extension_batch import BatchFeeder
                self._batch = BatchFeeder(self)
            return self._batch.status(batch_id)

    def phase(self, client_id: str, job_id: str, phase: str, tab_id: int,
              chat_path: str = "") -> dict:
        """Persist browser evidence before the next irreversible lifecycle step."""
        if phase not in {"submit_attempted", "remote_started", "result_captured"}:
            raise ValueError("invalid automation phase")
        if type(tab_id) is not int or tab_id < 0:
            raise ValueError("invalid browser tab identity")
        if not isinstance(chat_path, str) or (chat_path and not re.fullmatch(r"/c/[a-f0-9-]{36}", chat_path)):
            raise ValueError("invalid bound chat path")
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if not job or job.get("client_id") != client_id or job.get("state") != "claimed":
                raise ValueError("phase is not for this extension's claimed job")
            if job.get("preflight_only") or job.get("collect_only"):
                raise ValueError("this job does not submit a new remote request")
            bound_tab = job.get("browser_tab_id")
            if bound_tab is None or bound_tab != tab_id or self.client.get("tab_id") != tab_id:
                raise ValueError("phase is not from the exact paired job tab")
            current = job.get("phase", "prepared")
            if AUTOMATION_PHASE_RANK[phase] <= AUTOMATION_PHASE_RANK.get(current, 0):
                if chat_path and job.get("chat_path") not in {None, chat_path}:
                    raise ValueError("phase chat binding changed")
                return self.status(job_id)  # A repeated or late receipt changes nothing.
            if AUTOMATION_PHASE_RANK[phase] != AUTOMATION_PHASE_RANK.get(current, 0) + 1:
                raise ValueError("automation phase must advance exactly once")
            if phase in {"remote_started", "result_captured"}:
                if not chat_path:
                    raise ValueError("remote evidence requires the exact chat path")
                if job.get("chat_path") not in {None, chat_path}:
                    raise ValueError("job chat binding changed")
                job["chat_path"] = chat_path
            job["phase"] = phase
            job[f"{phase}_at"] = time.time()
            self._save(job)
            return self.status(job_id)

    def claim(self, client_id: str) -> dict:
        with self.lock:
            self._client(client_id)
            if any(job_holds_tab(job) for job in self.jobs.values()) or self.halted_job:
                return {}  # One tab, one job; a job that may have been sent stops the line until inspected.
            for job in self._waiting():
                if job["state"] == "waiting_for_batch":
                    blocker = self._batch.batches.get(job["blocked_by_batch"]) if self._batch else None
                    if not blocker or blocker["state"] != "complete":
                        if blocker and blocker["state"] == "running":
                            continue  # Only the owning batch may claim its next image.
                        return {}  # Stopped/missing ownership is not permission to proceed.
                    job.update(state="queued", client_id=client_id)
                    self._save(job)
                if job["state"] == "queued" and job["client_id"] == client_id:
                    if job.get("batch_id") and (self._batch is None or self._batch.batches.get(job["batch_id"], {}).get("state") != "running"):
                        if job.get("phase") == "prepared" and job.get("delivered", False) is False:
                            job.update(state="interrupted", error="Stopped batch canceled before delivery.")
                            self._save(job)
                            continue
                        return {}  # Ambiguous work cannot be canceled or delivered automatically.
                    if self._prepare_blocker(job):
                        return {}  # Remain FIFO and undelivered. A healthy heartbeat resumes this same request.
                    minimum_protocol = 4 if job.get("preflight_cleanup_only") or job.get("collect_only") else 3 if job.get("clear_preflight_uploads") else 2 if job.get("preflight_only") else 1 if job.get("images") or job.get("mode") == "edit" else 0
                    if (self.client.get("input_protocol", 0) < minimum_protocol or
                            (job.get("collect_only") and OUTPUT_BINDING_REVISIONS.get(self.client.get("worker_version")) !=
                             job.get("output_binding_revision", 1 if job.get("output_recovery_resumed") else 0))):
                        job.update(state="failed", error="Input protocol changed before delivery; nothing was delivered. Reload extension and paired tab.")
                        self._save(job)
                        raise ValueError(job["error"])
                    job["state"] = "claimed"
                    job["claimed_at"] = time.time()
                    job["delivered"] = True
                    job["phase_capable"] = self.client.get("tab_id") is not None
                    if job["phase_capable"]:
                        job["browser_tab_id"] = self.client["tab_id"]  # Bind when the job actually starts, not when it queued.
                    self._save(job)  # Persist BEFORE delivery. Never repeat on uncertain response.
                    claimed = {k: job[k] for k in ("job_id", "prompt", "expected_model", "mode", "preflight_only", "clear_preflight_uploads", "preflight_cleanup_only", "preflight_cleanup_resumed", "collect_only", "preserve_chat", "recovery_chat_path", "generation_timeout_seconds", "generation_baseline_seconds", "generation_timing_samples", "retry_count", "replaces_job_id", "auto_delete_saved_chat") if k in job}
                    if job.get("collect_only"):
                        if job.get("output_binding_revision") == 2:
                            claimed["output_binding_revision"] = 2
                        claimed["images"] = [dict(metadata) for metadata in job.get("images", [])]
                        return claimed  # Existing assistant outputs only; never deliver uploads again.
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
               preflight_uploads_cleared: bool = False, images_base64: list[str] | None = None,
               prompt_binding: dict | None = None, visible_variant_count: int | None = None,
               stall_recovered: bool = False) -> dict:
        if type(stall_recovered) is not bool:
            raise ValueError("invalid stall recovery flag")
        if type(cleanup_pending) is not bool or type(preflight_ready) is not bool or type(preflight_uploads_cleared) is not bool:
            raise ValueError("invalid cleanup flag")
        if visible_variant_count is not None and (type(visible_variant_count) is not int or not 1 <= visible_variant_count <= 100):
            raise ValueError("invalid visible variant count")
        if visible_variant_count is not None and (error is not None or preflight_ready):
            raise ValueError("variant count requires generated output")
        if chat_path is not None and (not isinstance(chat_path, str) or not re.fullmatch(r"/c/[a-f0-9-]{36}", chat_path)):
            raise ValueError("invalid generated chat path")
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if not job or job["client_id"] != client_id or job["state"] != "claimed":
                raise ValueError("job is not claimed by this extension; result was not accepted")
            binding_counts = {"exact_matching_descendant_count", "expected_chars", "observed_chars"}
            if prompt_binding is not None:
                binding_keys = binding_counts | {"root_match"}
                if job.get("output_binding_revision") == 2:
                    binding_keys.add("matcher_revision")
                if (not job.get("collect_only") or not isinstance(prompt_binding, dict) or
                        set(prompt_binding) != binding_keys or type(prompt_binding["root_match"]) is not bool or
                        (job.get("output_binding_revision") == 2 and
                         (type(prompt_binding.get("matcher_revision")) is not int or prompt_binding["matcher_revision"] != 2)) or
                        any(type(prompt_binding[key]) is not int or not 0 <= prompt_binding[key] <= 100000 for key in binding_counts)):
                    raise ValueError("invalid bounded original-prompt binding diagnostic")
                if error is None and not (prompt_binding["root_match"] or prompt_binding["exact_matching_descendant_count"]):
                    raise ValueError("recovery prompt binding did not match")
            if error is not None and (image_base64 is not None or images_base64 is not None):
                raise ValueError("an error cannot also contain generated images")
            if job.get("collect_only") and error is None and (cleanup_pending or chat_path != job.get("recovery_chat_path")):
                raise ValueError("recovery must preserve the exact inspected result chat")
            if (job.get("output_recovery_resumed") or job.get("output_binding_revision") == 2) and error is None and prompt_binding is None:
                raise ValueError("prompt-binding resume requires its native binding diagnostic")
            if preflight_uploads_cleared and not (job.get("clear_preflight_uploads") or job.get("failed_upload_cleanup")):
                raise ValueError("preflight upload clearing was not requested")
            if error is not None:
                job.update(state="failed", error=str(error)[:500], completed_at=time.time())
            elif job.get("failed_upload_cleanup"):
                if not preflight_ready or not preflight_uploads_cleared or image_base64 or images_base64 is not None or cleanup_pending or chat_path:
                    raise ValueError("failed-upload cleanup requires only an empty-composer no-Send receipt")
                job.update(state="failed", error=job["original_upload_error"], uploads_cleared=True,
                           submitted=False, generated=False, cleanup_status="not_requested",
                           draft_note="Inspected failed-job uploads removed; composer empty. Original image request was not completed.")
            elif job.get("preflight_only"):
                if not preflight_ready or image_base64 or images_base64 is not None or cleanup_pending or chat_path:
                    raise ValueError("preflight accepts only a no-Send readiness receipt, never media or cleanup")
                if job.get("clear_preflight_uploads") and not preflight_uploads_cleared:
                    raise ValueError("verified preflight upload clearing receipt is required")
                job.update(state="complete", phase="completed", preflight_ready=True, submitted=False, generated=False,
                           cleanup_status="not_requested", draft_note="Owned upload-only draft remains unsent; inspect before further work.")
                if preflight_uploads_cleared:
                    job.update(preflight_uploads_cleared=True,
                               draft_note="Owned preflight uploads removed after readiness verification; composer empty.")
            else:
                if preflight_ready:
                    raise ValueError("readiness receipt cannot complete a generation job")
                if job.get("browser_tab_id") is not None and not job.get("collect_only"):
                    if job.get("phase") != "result_captured":
                        raise ValueError("result requires durable submit, remote-start and capture receipts")
                    if chat_path != job.get("chat_path"):
                        raise ValueError("result chat does not match the bound remote chat")
                if cleanup_pending and job.get("auto_delete_saved_chat") is True and (
                        job.get("browser_tab_id") is None or job.get("phase") != "result_captured" or
                        not chat_path or chat_path != job.get("chat_path")):
                    raise ValueError("automatic cleanup requires exact bound job, tab and chat")
                if images_base64 is not None and image_base64 is not None:
                    raise ValueError("choose one image result representation")
                encoded = images_base64 if images_base64 is not None else [image_base64]
                if not isinstance(encoded, list) or not 1 <= len(encoded) <= 4:
                    raise ValueError("one to four ordered assistant outputs required")
                incomplete_variants = visible_variant_count is not None and visible_variant_count > len(encoded)
                if (job.get("preserve_chat") or len(encoded) > 1) and cleanup_pending:
                    raise ValueError("recovered or multiple outputs must preserve their chat")
                if incomplete_variants and cleanup_pending:
                    raise ValueError("unsaved visible outputs must preserve their chat")
                validated, total = [], 0
                for value in encoded:
                    if not isinstance(value, str) or not value or len(value) > (MAX_IMAGE * 4 // 3 + 8):
                        raise ValueError("missing or oversized image")
                    raw = base64.b64decode(value, validate=True)
                    total += len(raw)
                    if total > MAX_IMAGE:
                        raise ValueError("outputs exceed 25 MiB combined")
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format not in {"PNG", "JPEG", "WEBP"} or min(image.size) < 512 or image.width * image.height > 40_000_000:
                            raise ValueError("not a supported generated image of at least 512px")
                        image.verify()
                        suffix = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image.format]
                        dimensions = list(image.size)
                    validated.append((raw, suffix, dimensions))
                outputs = []
                for index, (raw, suffix, dimensions) in enumerate(validated, 1):
                    name = f"image.{suffix}" if len(validated) == 1 else f"image-{index:03d}.{suffix}"
                    path = self.root / job_id / name
                    digest = hashlib.sha256(raw).hexdigest()
                    if path.exists() or path.is_symlink():
                        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                            raise ValueError("existing output differs; preserve files and chat")
                    else:
                        from .extension_batch import durable_write
                        durable_write(path, raw, exclusive=True)
                    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise ValueError("saved output failed hash verification; preserve chat")
                    outputs.append({"order": index, "image_path": str(path), "dimensions": dimensions,
                                    "sha256": digest, "bytes": len(raw)})
                job.update(state="complete", phase="completed", completed_at=time.time(), outputs=outputs, output_count=len(outputs), source=source,
                           submitted=True, generated=True,
                           cleanup_status="preserved" if job.get("preserve_chat") or len(outputs) > 1 or incomplete_variants else "pending" if cleanup_pending else "not_requested",
                           quality_note="Rendered asset; original download resolution not verified.")
                if visible_variant_count is not None:
                    job["visible_variant_count"] = visible_variant_count
                if stall_recovered:
                    job["stall_recovered"] = True  # The image was there; only the unseen tab had stalled.
                if len(outputs) == 1:
                    job.update({key: outputs[0][key] for key in ("image_path", "dimensions", "sha256")})
                if chat_path is not None:
                    job["chat_path"] = chat_path
            if prompt_binding is not None:
                job["prompt_binding"] = dict(prompt_binding)
            self._save(job)
            if cleanup_pending and job.get("batch_id") and job.get("state") == "complete":
                record = self._batch.batches.get(job["batch_id"]) if self._batch else None
                running = next((p for p in record["progress"] if p.get("job_id") == job_id and p["state"] == "reserved"), None) if record and record["state"] == "running" else None
                try:
                    if not running:
                        raise ValueError("batch reservation unavailable")
                    self._batch.save_result(record, running, job)
                except (OSError, ValueError):
                    job.update(cleanup_status="failed", cleanup_error="Batch output copy unverified; chat preserved.")
                    self._save(job)
                    if record and record["state"] == "running":
                        self._batch._stop(record, "batch output copy unverified; inspect before continuing")
            return self.status(job_id)

    def timeout(self, client_id: str, job_id: str, chat_path: str, reason: str = "") -> dict:
        """End one proven-stalled generation and queue at most one replacement after exact-chat cleanup."""
        if reason not in TIMEOUT_REASONS:
            raise ValueError("invalid timeout reason")
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if (not job or job.get("client_id") != client_id or job.get("state") != "claimed" or
                    job.get("phase") != "remote_started" or job.get("chat_path") != chat_path):
                raise ValueError("adaptive timeout is not bound to this running job and exact chat")
            started = job.get("remote_started_at")
            timeout = job.get("generation_timeout_seconds")
            if not isinstance(started, (int, float)) or type(timeout) is not int or time.time() - started < timeout:
                raise ValueError("adaptive generation timeout has not elapsed")
            if job.get("batch_id"):
                job.update(state="failed", error="Batch timeout; inspect the original chat. No deletion or retry.", completed_at=time.time())
                self._save(job)
                raise ValueError("Batch timeout; inspect the original chat. No deletion or retry.")
            retry_count = job.get("retry_count", 0)
            unseen = reason == "page_hidden_unverified"  # Nobody could look: keep the chat, never regenerate blind.
            can_replace = (type(retry_count) is int and retry_count < MAX_TIMEOUT_REPLACEMENTS and
                           job.get("mode", "create") == "create" and not job.get("images") and not unseen)
            replacement = None
            if can_replace:
                replacement = {"job_id": uuid.uuid4().hex, "state": "queued", "phase": "prepared",
                               "prompt": job["prompt"], "account": self.account, "created_at": time.time(),
                               "expected_model": job["expected_model"], "client_id": client_id, "mode": "create",
                               "retry_count": retry_count + 1, "replaces_job_id": job_id,
                               **self._generation_timing(),
                               **({"auto_delete_saved_chat": True} if self.auto_delete_saved_chats else {})}
            job.update(state="failed", timed_out=True, inspected=True, submitted=True, generated=False,
                       completed_at=time.time(), cleanup_status="timeout_delete_pending",
                       error=f"Adaptive timeout after {timeout}s; deleting the exact stalled chat before replacement.")
            if reason:
                job["timeout_reason"] = reason
            if unseen:
                job.update(cleanup_status="preserved", error=f"Adaptive timeout after {timeout}s; the ChatGPT page stayed hidden, so the chat is kept unchecked.")
            if replacement:
                job["replacement_job_id"] = replacement["job_id"]
            self._save(job)
            if replacement:
                self.jobs[replacement["job_id"]] = replacement
                self._save(replacement)
            return self.status(job_id)

    def timeout_cleanup(self, client_id: str, job_id: str, deleted: bool, error: str = "",
                        output_visible: bool = False) -> dict:
        """Record the stalled-chat delete. A failed delete keeps the chat ("preserved") and never stops the line."""
        if type(deleted) is not bool or not isinstance(error, str) or type(output_visible) is not bool or (deleted and output_visible):
            raise ValueError("invalid timeout cleanup receipt")
        with self.lock:
            self._client(client_id)
            job = self.jobs.get(job_id)
            if (not job or job.get("client_id") != client_id or job.get("state") != "failed" or
                    job.get("timed_out") is not True or job.get("cleanup_status") != "timeout_delete_pending"):
                raise ValueError("timeout cleanup is not pending for this job")
            if deleted:
                job["cleanup_status"] = "deleted"
                self._save(job)
                return self.status(job_id)
            job.update(cleanup_status="preserved", previous_cleanup_status="timeout_delete_failed", delete_failed=True,
                       cleanup_error=error[:500] or "Timed-out chat deletion was not confirmed")
            revision = OUTPUT_BINDING_REVISIONS.get(self.client.get("worker_version"))
            if output_visible:
                # The delete refused because the chat shows a finished image: never regenerate, collect it instead.
                replacement = self.jobs.get(job.get("replacement_job_id") or "")
                if (replacement and replacement.get("state") == "queued" and replacement.get("phase") == "prepared"
                        and not replacement.get("delivered")):
                    replacement.update(state="interrupted", completed_at=time.time(),
                                       error="Replacement canceled: the original chat already shows a finished image.")
                    self._save(replacement)
                    job["canceled_replacement_job_id"] = job.pop("replacement_job_id")
                if revision is not None and not job.get("replacement_job_id") and not job.get("batch_id"):
                    job.update(state="queued", collect_only=True, preserve_chat=True, auto_recovered=True,
                               recovery_chat_path=job["chat_path"], output_binding_revision=revision,
                               recovered_from_error=job.pop("error"))
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

    def _queue_position(self, job: dict) -> int | None:
        """1 = next to run; counts the running job as a place ahead. None once the job has started."""
        if job.get("state") != "queued":
            return None
        ordered = sorted(self.jobs.values(), key=lambda j: (j.get("queue_sequence", 0), j.get("created_at", 0), j["job_id"]))
        position = next(i for i, other in enumerate(ordered) if other is job)
        ahead = sum(1 for index, other in enumerate(ordered) if other is not job and job_occupies_tab(other)
                    and (other["state"] != "queued" or index < position))
        return ahead + 1

    def _progress(self, job):
        progress = {}
        timing = {}
        for label, start, end in (("queue", "created_at", "claimed_at"),
                                  ("generation", "remote_started_at", "result_captured_at"),
                                  ("save", "result_captured_at", "completed_at")):
            a, b = job.get(start), job.get(end)
            if isinstance(a, (float, int)) and isinstance(b, (float, int)) and b >= a:
                timing[label] = round((b - a) * 1000)
        if timing:
            progress["stage_ms"] = timing
        if job["state"] in {"waiting_for_batch", "queued"} and isinstance(job.get("created_at"), (int, float)):
            progress["queue_wait_ms"] = max(0, round((time.time() - job["created_at"]) * 1000))
        if job["state"] == "waiting_for_batch":
            batch = self._batch.batches.get(job.get("blocked_by_batch")) if self._batch else None
            if batch and batch["state"] == "running":
                progress.update(wait_reason="waiting_for_batch", next_action="wait")
            elif not batch or batch["state"] != "complete":
                progress.update(wait_reason="blocking_batch_unavailable", next_action="inspect_blocking_batch")
        elif job["state"] == "queued":
            action = self._next_action()
            blocker = self._prepare_blocker(job)
            if blocker and action == blocker[1]:
                progress.update(wait_reason=blocker[0], next_action=action, user_message=blocker[2])
            elif action == "inspect_halted_job":
                progress.update(wait_reason="queue_halted", next_action="inspect_halted_job")
            elif action == "wait":
                progress.update(wait_reason="awaiting_worker", next_action="wait")
            elif action != "submit_via_mcp" and action not in (item[1] for item in _PREPARE_BLOCKERS.values()):
                progress.update(wait_reason="worker_not_ready", next_action=action)
        elif job['state'] == 'interrupted' and job.get('phase') == 'submit_attempted' and ended_uncertain(job):
            progress.update(next_action='inspect_halted_job', remote_delivery='unknown', safe_to_retry=False,
                user_message='The bridge has no saved image for this job. We do not know whether ChatGPT ever received '
                    'the request, or whether an image exists there. Check the original ChatGPT conversation. Even if '
                    'it is empty, the outcome is still unknown. Do not resubmit, delete, or start a replacement.',
                user_message_th='Bridge ยังไม่มีไฟล์ภาพของงานนี้ และไม่รู้ว่า ChatGPT ได้รับคำขอหรือสร้างภาพแล้วหรือไม่ '
                    'ให้ตรวจดูแชตเดิมของงานนี้เท่านั้น '
                    'แม้แชตว่างก็ยังสรุปไม่ได้ว่าไม่ได้ส่ง อย่าส่งซ้ำ อย่าลบแชต และอย่าเริ่มงานทดแทน')
        if 'user_message' in progress:
            progress['agent_action'] = 'report_to_user_and_stop'
        return progress

    def _receipt(self, job: dict, *, wait_timed_out: bool = False) -> dict:
        output = job.get("outputs")[0] if isinstance(job.get("outputs"), list) and job.get("outputs") else {}
        receipt = {"job_id": job["job_id"], "state": job["state"],
                   "phase": job.get("phase", "completed" if job["state"] == "complete" else "prepared"),
                   "image_path": job.get("image_path"), "dimensions": job.get("dimensions"),
                   "sha256": job.get("sha256"), "bytes": output.get("bytes"),
                   "chat_path": job.get("chat_path"), "preflight_ready": job.get("preflight_ready"),
                   "cleanup_status": job.get("cleanup_status"), "error": job.get("error"),
                   "submitted": job.get("submitted"), "generated": job.get("generated"),
                   "wait_timed_out": wait_timed_out}
        for key in ("generation_baseline_seconds", "generation_timeout_seconds", "generation_timing_samples",
                    "timed_out", "replacement_job_id", "replaces_job_id", "retry_count", "visible_variant_count", "cleanup_error",
                    "request_id", "payload_hash", "blocked_by_batch", "accepted_sequence"):
            if key in job:
                receipt[key] = job[key]
        copied = short_outputs(job)
        if copied:
            receipt["outputs"] = copied
            receipt["output_count"] = len(copied)
        if job.get("cleanup_confirmation"):
            receipt["cleanup_confirmation"] = job.get("cleanup_confirmation")
        if (position := self._queue_position(job)) is not None:
            receipt["queue_position"] = position
        return _agent_receipt(receipt, self._progress(job))

    def wait_for_job(self, job_id: str, timeout_seconds: int = 120) -> dict:
        """Block until the image is saved and cleanup has finished, or the job has failed. A timeout leaves the job unchanged."""
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be 1..120")
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("unknown job")
        deadline = time.monotonic() + timeout_seconds
        with self.finished:
            while True:
                job = self.jobs.get(job_id)
                if not job:
                    raise ValueError("unknown job")
                if job["state"] in TERMINAL and not job_occupies_tab(job):
                    return self._receipt(job)
                if job['state'] == 'queued' and self._prepare_blocker(job):
                    receipt = self._receipt(job)
                    if 'user_message' in receipt:
                        return receipt  # Report an actionable hold now; the original request stays queued.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._receipt(job, wait_timed_out=True)
                self.finished.wait(remaining)

    def status(self, job_id: str = "") -> dict:
        with self.lock:
            if not job_id:
                active = next((b for b in self._batch.batches.values() if b["state"] == "running"), None) if self._batch else None
                batch_summary = ({"batch_id": active["batch_id"], "state": active["state"],
                                  "total": len(active["progress"]),
                                  **{s: sum(p["state"] == s for p in active["progress"])
                                     for s in ("saved", "reserved", "untouched")}} if active else None)
                return {"account_source": "chrome_login", "paired": bool(self.client),
                        "active_batch": batch_summary,
                        "admission": "waiting_for_batch" if active else "fifo",
                        "cleanup_policy": "automatic_saved_chats" if self.auto_delete_saved_chats else "per_job_confirmation",
                        "account_binding": "uses the login in the paired Chrome tab",
                        "browser_binding": {"paired_tab": bool(self.client and self.client.get("tab_id") is not None),
                                            "paired_tab_id": self.client.get("tab_id") if self.client else None,
                                            "exact_job_tab_required": True, "exact_result_chat_required": True},
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
                        "next_action": self._next_action(),
                        "reload_requested": self.reload_requested,
                        "installed_extension_version": repo_extension_version(),
                        "line_halted": self.halted_job,
                        "queue_depth": sum(1 for j in self.jobs.values() if job_occupies_tab(j)),
                        "scheduler": {"policy": "fifo", "worker_tabs": 1,
                                      "capacity": MAX_WAITING_JOBS,
                                      "waiting": sum(j.get("state") == "queued" for j in self.jobs.values()),
                                      "waiting_for_batch": sum(j.get("state") == "waiting_for_batch" for j in self.jobs.values()),
                                      "in_flight_or_cleanup": sum(job_holds_tab(j) for j in self.jobs.values()),
                                      "rate_limit_policy": "not_configured"},
                        "extension_diagnostics": {
                            "worker_version": (self.client.get("worker_version") or None) if self.client else None,
                            "content_receiver": self.client.get("content_receiver", "unreported") if self.client else "unreported",
                            "content_protocol": self.client.get("input_protocol", 0) if self.client else 0,
                            "receiver_error": self.client.get("receiver_error", "") if self.client else "",
                            "tab_recovery": self.client.get("tab_recovery", "none") if self.client else "none",
                            "chatgpt_tabs": self.client.get("chatgpt_tabs", 0) if self.client else 0,
                            "upload_dom": self.client.get("upload_dom") if self.client else None,
                            "result_dom": self.client.get("result_dom") if self.client else None,
                            "prompt_dom": self.client.get("prompt_dom") if self.client else None},
                        "extension_online": bool(self.client and time.monotonic() - self.client["seen"] <= 90),
                        "jobs": [{k: j[k] for k in ("job_id", "state", "phase", "cleanup_status", "chat_path", "preflight_only", "clear_preflight_uploads") if k in j}
                                 for j in list(self.jobs.values())[-10:]]}
            if job_id not in self.jobs:
                raise ValueError("unknown job")
            job = self.jobs[job_id]
            view = {k: v for k, v in job.items() if k not in {"prompt", "client_id"}}
            view.update(self._progress(job))
            if (position := self._queue_position(job)) is not None:
                view["queue_position"] = position
            return view

    def client_status(self, client_id: str, job_id: str) -> dict:
        """Let the original extension clear terminal work, including after restart."""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or not isinstance(client_id, str) or not hmac.compare_digest(job["client_id"], client_id):
                raise ValueError("job does not belong to this extension")
            result = self.status(job_id)
            if job.get("cleanup_status") == "timeout_delete_pending":
                result["timeout_cleanup_job"] = {key: job[key] for key in
                    ("job_id", "prompt", "expected_model", "mode", "chat_path") if key in job}
            return result

    def resolve(self, job_id: str, clear_preflight_uploads: bool = False,
                clear_failed_uploads: bool = False, native_upload_names: list[str] | None = None,
                recover_outputs: bool = False, recovery_chat_path: str | None = None,
                inspected_chatgpt: bool = False) -> dict:
        """Explicit operator action after inspecting the upstream conversation."""
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("unknown job")
            if self.halted_job == job_id:
                # Plain inspection has no later recovery write. Persist before releasing the queue.
                if (recover_outputs is False and recovery_chat_path is None and
                        not clear_preflight_uploads and not clear_failed_uploads and native_upload_names is None):
                    self._save({**self.jobs[job_id], "inspected": True})
                self.jobs[job_id]["inspected"] = True
                self.halted_job = next((j["job_id"] for j in self.jobs.values() if ended_uncertain(j)), None)
            if type(recover_outputs) is not bool:
                raise ValueError("recover_outputs must be a boolean")
            if recovery_chat_path is not None and not recover_outputs:
                raise ValueError("recovery chat path requires explicit output recovery")
            if recover_outputs:
                job = self.jobs[job_id]
                if clear_preflight_uploads or clear_failed_uploads or native_upload_names is not None:
                    raise ValueError("output recovery cannot be combined with draft cleanup")
                if not isinstance(recovery_chat_path, str) or not re.fullmatch(r"/c/[a-f0-9-]{36}", recovery_chat_path):
                    raise ValueError("exact inspected result chat path is required")
                def recoverable_error(error):
                    return (isinstance(error, str) and
                            (error.startswith("Submission attempted. Multiple images returned;") or
                             error == "Submission attempted. Local bridge request failed: 400"))
                resume = (job.get("collect_only") is True and
                          job.get("error") == "Existing submitted-job recovery failed. Existing conversation does not match this job's prompt; image was not collected" and
                          recoverable_error(job.get("recovered_from_error")))
                # A failed collect-only attempt can be repeated once after the
                # data-image reader fix, still bound to the original saved chat.
                data_source_resume = (job.get("collect_only") is True and
                                      job.get("timed_out") is True and
                                      job.get("previous_cleanup_status") == "timeout_delete_failed" and
                                      job.get("error") == "Existing submitted-job recovery failed. Unsupported displayed image source" and
                                      job.get("recovery_chat_path") == recovery_chat_path and
                                      not job.get("data_source_recovery_resumed") and
                                      not job.get("replacement_job_id"))
                completed_timeout = (job.get("timed_out") is True and
                                     job.get("phase") == "remote_started" and
                                     job.get("submitted") is True and
                                     timeout_delete_failed(job) and not job.get("collect_only") and
                                     job.get("chat_path") == recovery_chat_path and
                                     not job.get("replacement_job_id"))
                if (job["state"] != "failed" or job.get("preflight_only") or
                        (job.get("collect_only") and not resume and not data_source_resume) or
                        (not resume and not data_source_resume and not completed_timeout and not recoverable_error(job.get("error")))):
                    raise ValueError("only the inspected submitted multiple-image failure or HTTP 400 failure can be recovered once")
                if (not self.client or time.monotonic() - self.client["seen"] > 90 or
                        self.client["client_id"] != job["client_id"] or self.client.get("worker_version") not in OUTPUT_BINDING_REVISIONS):
                    raise ValueError("original online extension 0.1.20 or a supported newer matcher is required")
                revision = OUTPUT_BINDING_REVISIONS[self.client["worker_version"]]
                if data_source_resume and self.client["worker_version"] not in {"0.1.38", "0.1.39"}:
                    raise ValueError("data-image recovery requires the reloaded 0.1.38 or 0.1.39 extension")
                previous_revision = job.get("output_binding_revision", 1 if job.get("prompt_binding") or job.get("output_recovery_resumed") else 0)
                if resume and revision <= previous_revision:
                    raise ValueError("prompt-binding resume needs 0.1.21 or newer with an untried matcher revision; unchanged retry refused")
                if resume and job.get("recovery_chat_path") != recovery_chat_path:
                    raise ValueError("prompt-binding resume must inspect the original result chat")
                if any(j["state"] not in TERMINAL or j.get("cleanup_status") in {"pending", "confirmation_required"} for j in self.jobs.values()):
                    raise ValueError("finish existing work before output recovery")
                if max(self.jobs, key=lambda key: (self.root / key / "state.json").stat().st_mtime_ns) != job_id:
                    raise ValueError("only the latest inspected output failure may be recovered")
                if (self.client.get("result_dom") or {}).get("chat_path") != recovery_chat_path:
                    raise ValueError("paired tab is not the inspected result chat")
                inspected = self.client["result_dom"]
                if (not inspected.get("assistant_body_found") or inspected.get("busy") or
                        not 1 <= inspected.get("assistant_images", 0) <= 4 or
                        inspected.get("user_headings") != 1 or inspected.get("assistant_headings") != 1):
                    raise ValueError("inspect the completed single-turn assistant outputs before recovery")
                if completed_timeout:
                    job["previous_cleanup_status"] = "timeout_delete_failed"
                    job["cleanup_status"] = "preserved"
                previous_error = job.pop("error")
                job.update(state="queued", collect_only=True, preserve_chat=True, recovery_chat_path=recovery_chat_path,
                           recovery_dom=dict(inspected), output_binding_revision=revision)
                if resume or data_source_resume:
                    job.update(output_recovery_resumed=True, previous_recovery_error=previous_error)
                    if data_source_resume:
                        job["data_source_recovery_resumed"] = True
                    if job.get("prompt_binding") is not None:
                        job["previous_prompt_binding"] = job.pop("prompt_binding")
                else:
                    job["recovered_from_error"] = previous_error
                self._save(job)
                return self.status(job_id)
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
            job = self.jobs[job_id]
            if (inspected_chatgpt is True and job["state"] == "failed" and
                    job.get("cleanup_status") == "timeout_delete_failed"):  # Legacy records only.
                job["previous_cleanup_status"] = job["cleanup_status"]
                job["cleanup_status"] = "preserved"
                self._save(job)
            elif job["state"] not in TERMINAL:
                job.update(state="interrupted", error="Operator resolved uncertain work; no automatic resubmission.")
                self._save(job)
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
                    result = queue.pair(data["client_id"], data.get("account"), data.get("visible_model", ""),
                                        data.get("input_protocol", 0), data.get("tab_id"),
                                        data.get("retry_timeout_cleanup", False), data.get("automatic", False))
                elif self.path == "/heartbeat":
                    result = queue.heartbeat(**data)
                elif self.path == "/phase":
                    result = queue.phase(**data)
                elif self.path == "/next":
                    result = queue.claim(data["client_id"])
                elif self.path == "/result":
                    result = queue.result(**data)
                elif self.path == "/timeout":
                    result = queue.timeout(**data)
                elif self.path == "/timeout-cleanup":
                    result = queue.timeout_cleanup(**data)
                elif self.path == "/cleanup":
                    result = queue.cleanup(**data)
                elif self.path == "/cleanup-confirmation":
                    result = queue.claim_delete_confirmation(**data)
                elif self.path == "/state":
                    result = queue.client_status(data["client_id"], data["job_id"])
                elif self.path == "/agent/status":
                    result = queue.status(**data)
                elif self.path == "/agent/wait":
                    result = queue.wait_for_job(data["job_id"], data.get("timeout_seconds", 120))
                elif self.path == "/agent/image":
                    if any(k.startswith("_") for k in data):
                        raise ValueError("internal queue arguments are not accepted")
                    result = queue.submit(**data)
                elif self.path == "/agent/batch-start":
                    result = queue.batch_start(**data)
                elif self.path == "/agent/enqueue":
                    result = queue.enqueue(**data)
                elif self.path == "/agent/batch-status":
                    result = queue.batch_status(**data)
                elif self.path == "/agent/confirm-delete":
                    result = queue.confirm_delete(**data)
                elif self.path == "/agent/reload":
                    result = queue.request_reload()
                elif self.path == "/agent/resolve":
                    if data.get("inspected_chatgpt") is not True:
                        raise ValueError("inspect ChatGPT before resolving uncertain work")
                    result = queue.resolve(data["job_id"], data.get("clear_preflight_uploads", False),
                                           data.get("clear_failed_uploads", False), data.get("native_upload_names"),
                                           data.get("recover_outputs", False), data.get("recovery_chat_path"),
                                           inspected_chatgpt=True)
                else:
                    return self.reply(404, {"error": "unknown route"})
                self.reply(200, result)
            except ValueError as error:
                message = str(error)
                if not message or len(message) > 300:
                    message = "invalid request or job state; inspect MCP status"
                self.reply(400, {"error": message})
            except (KeyError, TypeError, OSError):
                self.reply(400, {"error": "invalid request or job state; inspect MCP status"})
    return Handler


def _agent_receipt(receipt, progress):
    if progress.get('agent_action') and progress.get('user_message'):
        if not receipt.get('generation_timing_samples'):
            # Internal scheduler defaults with no observations are not customer ETAs.
            receipt.pop('generation_baseline_seconds', None)
        return {'agent_action': progress['agent_action'], 'user_message': progress['user_message'],
                **receipt, **progress}
    return {**receipt, **progress}


def compact_status(raw: dict) -> dict:
    """Short MCP receipt. Drops prompts, unbounded diagnostics, and job history."""
    if not isinstance(raw, dict):
        raise ValueError("invalid status")
    if "job_id" in raw or "state" in raw:
        output = raw.get("outputs")[0] if isinstance(raw.get("outputs"), list) and raw.get("outputs") else {}
        receipt = {"job_id": raw.get("job_id"), "state": raw.get("state"),
                   "phase": raw.get("phase"),
                   "image_path": raw.get("image_path"), "dimensions": raw.get("dimensions"),
                   "sha256": raw.get("sha256"),
                   "bytes": output.get("bytes") if isinstance(output, dict) else raw.get("bytes"),
                   "chat_path": raw.get("chat_path"), "preflight_ready": raw.get("preflight_ready"),
                   "submitted": raw.get("submitted"), "generated": raw.get("generated"),
                   "cleanup_status": raw.get("cleanup_status"), "error": raw.get("error"),
                   "wait_timed_out": raw.get("wait_timed_out", False)}
        if type(raw.get("browser_tab_id")) is int and raw["browser_tab_id"] >= 0:
            receipt["browser_tab_id"] = raw["browser_tab_id"]
        if raw.get("queue_position") is not None:
            receipt["queue_position"] = raw["queue_position"]
        for key in ("generation_baseline_seconds", "generation_timeout_seconds", "generation_timing_samples",
                    "timed_out", "replacement_job_id", "replaces_job_id", "retry_count", "visible_variant_count", "cleanup_error",
                    "request_id", "payload_hash", "blocked_by_batch", "accepted_sequence"):
            if key in raw:
                receipt[key] = raw[key]
        progress = {key: raw[key] for key in ("wait_reason", "next_action", "stage_ms", "queue_wait_ms", "user_message", "agent_action", "remote_delivery", "safe_to_retry", "user_message_th") if key in raw}
        copied = short_outputs(raw)
        if copied:
            receipt["outputs"] = copied
            receipt["output_count"] = len(copied)
        if raw.get("cleanup_confirmation"):
            receipt["cleanup_confirmation"] = raw.get("cleanup_confirmation")
        return _agent_receipt(receipt, progress)
    brief = {"account_source": "chrome_login", "paired": raw.get("paired"),
             "running_extension_version": (raw.get("extension_diagnostics") or {}).get("worker_version"),
             "extension_online": raw.get("extension_online"), "next_action": raw.get("next_action"),
             "transport": raw.get("transport"), "browser_binding": raw.get("browser_binding"),
             "preflight_available": (raw.get("input_capabilities") or {}).get("preflight_only"),
             **{key: raw[key] for key in ("queue_depth", "line_halted", "installed_extension_version", "scheduler", "active_batch", "admission") if raw.get(key) is not None}}
    diagnostics = raw.get("extension_diagnostics") or {}
    receiver = diagnostics.get("content_receiver")
    receiver_error = diagnostics.get("receiver_error")
    brief["receiver_readiness"] = {
        "tab_ready": raw.get("tab_ready") if type(raw.get("tab_ready")) is bool else None,
        "tab_idle": raw.get("tab_idle") if type(raw.get("tab_idle")) is bool else None,
        "tab_error_present": bool(raw.get("tab_error")),
        "content_receiver": receiver if receiver in {"unreported", "available", "tab_missing", "wrong_origin", "unavailable", "invalid_reply"} else "unreported",
        "receiver_error": receiver_error if receiver_error in {"", "tab_missing", "wrong_origin", "no_receiver", "port_closed", "message_failed", "invalid_reply"} else "unreported",
    }
    jobs = raw.get("jobs") if isinstance(raw.get("jobs"), list) else []
    open_job = next((job for job in jobs if isinstance(job, dict) and job_occupies_tab(job)), None)
    if open_job:
        brief.update(job_id=open_job.get("job_id"), state=open_job.get("state"),
                     phase=open_job.get("phase"), cleanup_status=open_job.get("cleanup_status"))
    return brief


RUN_TIMEOUT_DEFAULT = 300
RUN_TIMEOUT_MAX = 3600
_ADMISSION_CAUSES = (("different payload", "request_id_conflict"), ("pair a logged-in", "extension_offline"),
                     ("worker unavailable", "extension_offline"), ("reload the", "extension_version_mismatch"),
                     ("queue is full", "queue_full"), ("finish timeout cleanup", "cleanup_in_progress"))


def _run_failure(record: dict) -> tuple[str, bool]:
    """(cause, safe_to_retry). Safe means a new request cannot duplicate work already sent to ChatGPT."""
    error = record.get("error") or ""
    if "Owner action required" in error:
        return "verification_required", False
    if record.get("timed_out"):
        reason = record.get("timeout_reason", "")
        if reason == "page_hidden_unverified":
            return "stalled_hidden_tab", False
        if reason == "no_image_returned":
            return "chatgpt_no_image", True
        return "generation_timeout", reason == "still_generating"
    never_sent = record.get("phase", "prepared") == "prepared" and (not record.get("delivered") or record.get("phase_capable"))
    if error.startswith("Not submitted") or "nothing reached ChatGPT" in error or "nothing was delivered" in error or never_sent:
        return "not_submitted", True
    if error.startswith("Existing submitted-job recovery failed"):
        return "recovery_failed", False
    if "Timed out before a remote chat was bound" in error or record.get("phase") == "submit_attempted":
        return "delivery_unknown", False
    if "More than four" in error or "Multiple images" in error:
        return "unexpected_outputs", False
    if any(text in error for text in ("could not be read", "changed during collection", "Unsupported displayed image", "could not be saved")):
        return "output_unreadable", False
    if record.get("state") == "interrupted":
        return "interrupted_unknown", False
    return "failed_unknown", False


def save_output(target: Path, raw: bytes, digest: str, job_id: str, write) -> None:
    """Write raw to target. Calls for the same out_path queue on one file lock (across threads and
    processes): a later call waits for the earlier one, then skips if the target already holds these bytes."""
    import fcntl, tempfile
    lock_dir = Path(tempfile.gettempdir()) / "gpt-bridge-save-locks"
    lock_dir.mkdir(exist_ok=True)
    lock_name = hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:32] + ".lock"
    with open(lock_dir / lock_name, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)  # Blocks until the earlier writer is done: a queue, never a cancel.
        try:
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                return
            temporary = target.with_name(f".{target.name}.{job_id}.{secrets.token_hex(4)}.tmp")
            write(temporary, raw)
            os.replace(temporary, target)  # Atomic: out_path is either the old file or the complete new image.
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_image(queue, prompt: str, out_path: str, request_id: str, images=None, mode: str = "create",
              cleanup: str = "delete_on_success", timeout_seconds: int = RUN_TIMEOUT_DEFAULT, *, _sleep=time.sleep) -> dict:
    """One call for one image: submit once, wait, recover, save to out_path, clean up. Works on the owner queue or a client.
    The same request_id always continues the same job; it never submits twice."""
    result = {"status": "failed", "request_id": request_id, "job_id": None, "out_path": None, "width": None, "height": None,
              "sha256": None, "chat_path": None, "cleanup_status": None, "error": None, "cause": None, "safe_to_retry": False}

    def finish(status, cause, record=None, **extra):
        if record:
            status_name = record.get("cleanup_status")
            result.update(job_id=record.get("job_id"), chat_path=record.get("chat_path"),
                          cleanup_status={"failed": "preserved", "not_requested": "kept"}.get(status_name, status_name))
            if status_name == "failed" or record.get("delete_failed"):
                result["delete_failed"] = True
        result.update(status=status, cause=cause, **extra)
        return result

    if cleanup not in {"delete_on_success", "keep"}:
        return finish("failed", "invalid_request", error="cleanup must be delete_on_success or keep", safe_to_retry=True)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= RUN_TIMEOUT_MAX:
        return finish("failed", "invalid_request", error=f"timeout_seconds must be 1..{RUN_TIMEOUT_MAX}", safe_to_retry=True)
    target = Path(out_path) if isinstance(out_path, str) else None
    if (target is None or not target.is_absolute() or ".." in target.parts or not target.parent.is_dir()
            or target.is_symlink() or target.is_dir()):
        return finish("failed", "invalid_out_path", safe_to_retry=True,
                      error="out_path must be an absolute file path in an existing folder, not a symlink or folder")
    deadline = time.monotonic() + timeout_seconds
    try:
        receipt = queue.enqueue(request_id, prompt, images, mode, cleanup=cleanup)
    except ValueError as error:
        message = str(error)
        cause = next((name for text, name in _ADMISSION_CAUSES if text in message), "not_accepted")
        return finish("failed", cause, error=message[:300], safe_to_retry=cause != "request_id_conflict")
    job_id, followed = receipt["job_id"], set()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            record = queue.status(job_id)
            return finish("running", record.get("wait_reason") or "still_running", record,
                          resume="Call run again with the same request_id. It continues this job and never resubmits.",
                          **({"user_message": record["user_message"]} if record.get("user_message") else {}))
        receipt = queue.wait_for_job(job_id, max(1, min(120, int(remaining))))
        if receipt.get("state") not in TERMINAL or receipt.get("wait_timed_out"):
            if receipt.get("state") == "queued" and receipt.get("user_message"):
                _sleep(min(5, max(0, deadline - time.monotonic())))  # A known hold returns at once; do not spin.
            continue
        record = queue.status(job_id)
        replacement = record.get("replacement_job_id")
        if record["state"] != "complete" and replacement and replacement not in followed:
            followed.add(job_id)
            job_id = replacement  # The timed-out chat was handled; its one replacement carries the request.
            continue
        break
    if record["state"] != "complete":
        cause, safe = _run_failure(record)
        return finish("failed", cause, record, error=record.get("error"), safe_to_retry=safe)
    outputs = record.get("outputs") or []
    source = record.get("image_path") or (outputs[0].get("image_path") if outputs else None)
    try:
        from .extension_batch import durable_write, read_regular
        raw = read_regular(source)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != (record.get("sha256") or outputs[0].get("sha256")):
            raise ValueError("saved image changed after verification")
        save_output(target, raw, digest, record["job_id"], durable_write)
    except (OSError, ValueError, TypeError, IndexError) as error:
        return finish("failed", "save_failed", record, safe_to_retry=False, image_path=source,
                      error=f"Image is saved in the job folder but could not be written to out_path: {error}"[:300])
    dimensions = record.get("dimensions") or (outputs[0].get("dimensions") if outputs else None) or [None, None]
    wanted_delete = record.get("cleanup_requested") == "delete_on_success"
    cause = ("false_stall_recovered" if record.get("stall_recovered") else
             "timeout_output_recovered" if record.get("auto_recovered") else
             "delete_failed_preserved" if wanted_delete and record.get("cleanup_status") == "failed" else
             "multiple_outputs_preserved" if len(outputs) > 1 else "ok")
    extra = {"output_count": len(outputs), "outputs": [item.get("image_path") for item in outputs]} if len(outputs) > 1 else {}
    if followed:
        extra["replaced_job_ids"] = sorted(followed)
    return finish("done", cause, record, out_path=str(target), width=dimensions[0], height=dimensions[1],
                  sha256=digest, image_path=source, **extra)


def create_mcp(queue):
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("gpt-bridge", instructions="For one image call run(prompt, out_path, request_id): it submits once, waits, saves the file and cleans up; if status is running, call run again with the same request_id. Step by step instead: Book one image with enqueue; if the user supplied an order or ticket reference for it, use that exact reference as request_id. Same ID and arguments return the same job. For an existing receipt call job with its job_id. At report_to_user_and_stop, deliver user_message (user_message_th for Thai if present), without adding troubleshooting steps. Unknown remote delivery stays unknown even after an empty chat. Never retry when safe_to_retry is false.")

    @server.tool()
    def status(job_id: str = "") -> dict:
        """Paired Chrome tab, or one job. Uses its current ChatGPT login; no account selection. Returns paired, extension_online, next_action. With job_id, returns state and image_path."""
        return compact_status(queue.status(job_id))

    @server.tool()
    def wait(job_id: str, timeout_seconds: int = 120) -> dict:
        """Wait for ongoing work only. Do not call after report_to_user_and_stop. An actionable hold returns immediately. A timeout does not resubmit or cancel a job."""
        return queue.wait_for_job(job_id, timeout_seconds)

    @server.tool()
    def job(job_id: str) -> dict:
        """Read the original image job without changing it. At report_to_user_and_stop, return its ready-to-share user_message without extrapolating from the internal phase. submit_attempted is a local intent marker, NOT evidence the request was sent. Only a saved image_path confirms a local result."""
        return compact_status(queue.status(job_id))

    @server.tool()
    def batch_start(batch_id: str, items: list[dict], destination: str, attempts: str) -> dict:
        """Start one immutable prompt batch with durable markers; destination and attempts must be existing absolute directories."""
        return queue.batch_start(batch_id, items, destination, attempts)

    @server.tool()
    def batch_status(batch_id: str) -> dict:
        """Read the durable batch and per-item state without submitting."""
        return queue.batch_status(batch_id)

    @server.tool()
    def enqueue(request_id: Annotated[str, Field(description="Stable ID for this image. Use the supplied order or ticket reference verbatim; never append a suffix or generate a new ID for a retry. Allowed: 1–100 ASCII letters, digits, hyphens, underscores.")], prompt: str, images: list[LocalImageInput] | None = None,
                mode: Literal["create", "edit"] = "create") -> dict:
        """Book one image once. Use the caller's exact order reference. If the receipt says report_to_user_and_stop, give the user its message now with no more tool calls. Otherwise use job or wait on the returned job_id. Never also generate this request."""
        return compact_status(queue.enqueue(request_id, prompt, images, mode))

    @server.tool()
    async def run(prompt: str, out_path: Annotated[str, Field(description="Absolute file path for the image. An existing file is replaced.")],
                  request_id: Annotated[str, Field(description="Stable ID for this image. The same ID always continues the same job. Allowed: 1-100 ASCII letters, digits, hyphens, underscores.")],
                  images: list[LocalImageInput] | None = None, mode: Literal["create", "edit"] = "create",
                  cleanup: Literal["delete_on_success", "keep"] = "delete_on_success",
                  timeout_seconds: Annotated[int, Field(ge=1, le=RUN_TIMEOUT_MAX)] = RUN_TIMEOUT_DEFAULT) -> dict:
        """One image, one call: submit once, wait, recover, save to out_path, clean up the chat. Returns status done, failed or running. On running, call run again with the same request_id; it never resubmits. cause says why; retry with a new request_id only when safe_to_retry is true."""
        import anyio
        return await anyio.to_thread.run_sync(
            lambda: run_image(queue, prompt, out_path, request_id, images, mode, cleanup, timeout_seconds))

    @server.tool()
    def preflight(prompt: str, images: list[LocalImageInput], mode: Literal["create", "edit"] = "create",
                  clear_uploads: bool = True) -> dict:
        """Verify ordered native uploads without Send or generation. By default removes only those verified test uploads."""
        return compact_status(queue.submit(prompt, "Create image", mode, images, True, clear_uploads))

    @server.tool()
    def generate(prompt: str, images: list[LocalImageInput] | None = None) -> dict:
        """Create one image. images are optional references. Then call wait with the returned job_id."""
        return compact_status(queue.submit(prompt, "Create image", "create", images, False, False))

    @server.tool()
    def edit(prompt: str, images: list[LocalImageInput]) -> dict:
        """Edit one image. images must include one source. Then call wait with the returned job_id."""
        return compact_status(queue.submit(prompt, "Create image", "edit", images, False, False))

    @server.tool()
    def confirm_delete(job_id: str, owner_confirmed: bool = False) -> dict:
        """Delete one saved chat after the owner approved that exact chat. Not used when cleanup is automatic."""
        return compact_status(queue.confirm_delete(job_id, owner_confirmed))

    @server.tool()
    def resolve(job_id: str, inspected_chatgpt: StrictBool = False, clear_preflight_uploads: StrictBool = False,
                clear_failed_uploads: StrictBool = False, native_upload_names: list[str] | None = None,
                recover_outputs: StrictBool = False, recovery_chat_path: str | None = None) -> dict:
        """Stop a stuck job after the ChatGPT tab was inspected. Does not send again."""
        if inspected_chatgpt is not True:
            raise ValueError("inspect ChatGPT before resolving uncertain work")
        if recover_outputs or recovery_chat_path is not None:
            return compact_status(queue.resolve(job_id, clear_preflight_uploads, clear_failed_uploads, native_upload_names, recover_outputs, recovery_chat_path, inspected_chatgpt=True))
        if clear_failed_uploads or native_upload_names is not None:
            return compact_status(queue.resolve(job_id, clear_preflight_uploads, clear_failed_uploads, native_upload_names, inspected_chatgpt=True))
        return compact_status(queue.resolve(job_id, clear_preflight_uploads, inspected_chatgpt=True))

    return server


def read_token(root: Path) -> str:
    token_path = root / "extension-token"
    if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
        raise ValueError("extension token file must be private and not a symlink")
    token = token_path.read_text().strip()
    if len(token) < 32:
        raise ValueError("invalid local pairing token")
    return token


def default_data_dir() -> Path:
    base = Path.home() / ".local/share/gpt-bridge/extension"
    # Preserve the existing queue and pairing secret; the old folder name is not an account selector.
    legacy = base / "second"
    return legacy if legacy.exists() else base / "chrome"


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="GPT Bridge extension MCP — uses the ChatGPT login in your paired Chrome tab")
    parser.add_argument("--account", choices=["second"], help=argparse.SUPPRESS)  # Legacy storage namespace, not a login selector.
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument("--connect", action="store_true",
                           help="Share an already running local extension worker; do not create another queue or listener")
    lifecycle.add_argument("--serve", action="store_true",
                           help="Run only the loopback worker, independent of MCP stdio; agent hosts use --connect")
    parser.add_argument("--batch-run-root", type=Path, action="append", default=[],
                        help="Explicitly allow a batch run directory containing prompts.json, generation_log.tsv, raw and receipts; repeatable")
    parser.add_argument("--auto-delete-saved-chats", action="store_true",
                        help="Owner opt-in: permanently delete only new Bridge-created image chats after validated local save, without per-image prompts")
    args = parser.parse_args(argv)
    if args.connect and args.batch_run_root:
        parser.error("batch run allowlist belongs to the owning worker")
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
    namespace = args.account or ("second" if root.name == "second" else "chrome")
    queue = ExtensionQueue(root, namespace, auto_delete_saved_chats=args.auto_delete_saved_chats, batch_allowed_runs=args.batch_run_root)
    token_path = queue.root / "extension-token"
    if not token_path.exists():
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(secrets.token_urlsafe(32))
    try:
        token = read_token(root)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    http = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(queue, token, PORT))
    if args.serve:
        try:
            http.serve_forever()
        finally:
            http.server_close()
        return
    server = create_mcp(queue)
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
