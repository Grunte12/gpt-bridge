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
OPEN_CLEANUP = {"pending", "confirmation_required"}


def job_occupies_tab(job: dict) -> bool:
    return job.get("state") not in TERMINAL or job.get("cleanup_status") in OPEN_CLEANUP


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
OUTPUT_BINDING_REVISIONS = {"0.1.20": 0, "0.1.21": 1, "0.1.22": 1, "0.1.23": 2, "0.1.24": 2, "0.1.25": 2, "0.1.26": 2, "0.1.27": 2, "0.1.28": 2, "0.1.29": 2, "0.1.30": 2}
TAB_RECOVERY = {"none", "rebound", "unmatched"}


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
                recover_outputs: bool = False, recovery_chat_path: str | None = None) -> dict:
        return self.call("resolve", {"job_id": job_id, "inspected_chatgpt": True,
                                    **({"clear_preflight_uploads": clear_preflight_uploads} if clear_preflight_uploads is not False else {}),
                                    **({"clear_failed_uploads": clear_failed_uploads} if clear_failed_uploads is not False else {}),
                                    **({"native_upload_names": native_upload_names} if native_upload_names is not None else {}),
                                    **({"recover_outputs": True} if recover_outputs else {}),
                                    **({"recovery_chat_path": recovery_chat_path} if recovery_chat_path is not None else {})})

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
        self.finished = threading.Condition(self.lock)
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
        with self.finished:
            self.finished.notify_all()

    def pair(self, client_id: str, account: str, visible_model: str = "", input_protocol: int = 0) -> dict:
        if account != self.account or not isinstance(client_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", client_id):
            raise ValueError("account or client identity mismatch")
        if not isinstance(visible_model, str) or len(visible_model) > 100:
            raise ValueError("invalid visible model label")
        if type(input_protocol) is not int or input_protocol not in {0, 1, 2, 3, 4}:
            raise ValueError("invalid input protocol")
        with self.lock:
            if any(job_occupies_tab(j) for j in self.jobs.values()):
                raise ValueError("finish the current job before pairing again; call wait and do not send again")
            self.client = {"client_id": client_id, "seen": time.monotonic(), "visible_model": visible_model,
                           "tab_ready": True, "input_protocol": input_protocol}
            return {"paired": True, "account": self.account, "identity": "owner-confirmed, not independently verified"}

    def heartbeat(self, client_id: str, account: str, visible_model: str = "Create image",
                  tab_ready: bool = False, input_protocol: int = 0,
                  tab_idle: bool | None = None, tab_error: str = "",
                  worker_version: str = "", content_receiver: str = "unreported",
                  receiver_error: str = "", upload_dom: dict | None = None, result_dom: dict | None = None,
                  prompt_dom: dict | None = None, tab_recovery: str = "none", chatgpt_tabs: int = 0) -> dict:
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
        if not isinstance(tab_recovery, str) or tab_recovery not in TAB_RECOVERY:
            raise ValueError("invalid tab recovery diagnostic")
        if type(chatgpt_tabs) is not int or not 0 <= chatgpt_tabs <= 20:
            raise ValueError("invalid ChatGPT tab count")
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
            if self.client is None:
                self.pair(client_id, account, visible_model, input_protocol)
            else:
                self._client(client_id)
            self.client.update(visible_model=visible_model, tab_ready=tab_ready, input_protocol=input_protocol,
                               tab_idle=tab_idle, tab_error=tab_error, worker_version=worker_version,
                               content_receiver=content_receiver, receiver_error=receiver_error,
                               tab_recovery=tab_recovery, chatgpt_tabs=chatgpt_tabs,
                               upload_dom=dict(upload_dom) if upload_dom is not None else None,
                               result_dom=dict(result_dom) if result_dom is not None else None,
                               prompt_dom=json.loads(json.dumps(prompt_dom)) if prompt_dom is not None else None)
            return self.status()

    def _next_action(self) -> str:
        """One machine-readable next step. Never includes page content or a tab URL."""
        if any(job_occupies_tab(job) for job in self.jobs.values()):
            return "wait"
        if not self.client or time.monotonic() - self.client.get("seen", 0) > 90:
            return "wait_for_extension"
        tabs = self.client.get("chatgpt_tabs", 0)
        recovery = self.client.get("tab_recovery", "none")
        receiver = self.client.get("content_receiver", "unreported")
        if (self.client.get("tab_error") or "").startswith("Owner action required"):
            return "verify_second_tab"
        if recovery == "unmatched" or receiver == "wrong_origin" or (receiver == "tab_missing" and tabs > 0):
            return "confirm_second_tab"
        if receiver == "tab_missing":
            return "open_second_tab"
        if receiver == "unavailable" and self.client.get("receiver_error") == "no_receiver":
            return "refresh_paired_tab_once"
        if self.client.get("tab_ready") is True or self.client.get("content_receiver") == "available":
            return "submit_via_mcp"
        return "wait_for_tab"

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
            blocker = next((job for job in self.jobs.values() if job_occupies_tab(job)), None)
            if blocker:
                raise ValueError(f"one image job at a time; call wait for {blocker['job_id']}. Do not resolve or send again.")
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
                    minimum_protocol = 4 if job.get("preflight_cleanup_only") or job.get("collect_only") else 3 if job.get("clear_preflight_uploads") else 2 if job.get("preflight_only") else 1 if job.get("images") or job.get("mode") == "edit" else 0
                    if (self.client.get("input_protocol", 0) < minimum_protocol or
                            (job.get("collect_only") and OUTPUT_BINDING_REVISIONS.get(self.client.get("worker_version")) !=
                             job.get("output_binding_revision", 1 if job.get("output_recovery_resumed") else 0))):
                        job.update(state="failed", error="Input protocol changed before delivery; nothing was delivered. Reload extension and paired tab.")
                        self._save(job)
                        raise ValueError(job["error"])
                    job["state"] = "claimed"
                    self._save(job)  # Persist BEFORE delivery. Never repeat on uncertain response.
                    claimed = {k: job[k] for k in ("job_id", "prompt", "expected_model", "mode", "preflight_only", "clear_preflight_uploads", "preflight_cleanup_only", "preflight_cleanup_resumed", "collect_only", "preserve_chat", "recovery_chat_path") if k in job}
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
               prompt_binding: dict | None = None) -> dict:
        if type(cleanup_pending) is not bool or type(preflight_ready) is not bool or type(preflight_uploads_cleared) is not bool:
            raise ValueError("invalid cleanup flag")
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
                job.update(state="failed", error=str(error)[:500])
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
                job.update(state="complete", preflight_ready=True, submitted=False, generated=False,
                           cleanup_status="not_requested", draft_note="Owned upload-only draft remains unsent; inspect before further work.")
                if preflight_uploads_cleared:
                    job.update(preflight_uploads_cleared=True,
                               draft_note="Owned preflight uploads removed after readiness verification; composer empty.")
            else:
                if preflight_ready:
                    raise ValueError("readiness receipt cannot complete a generation job")
                if images_base64 is not None and image_base64 is not None:
                    raise ValueError("choose one image result representation")
                encoded = images_base64 if images_base64 is not None else [image_base64]
                if not isinstance(encoded, list) or not 1 <= len(encoded) <= 4:
                    raise ValueError("one to four ordered assistant outputs required")
                if (job.get("preserve_chat") or len(encoded) > 1) and cleanup_pending:
                    raise ValueError("recovered or multiple outputs must preserve their chat")
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
                        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(descriptor, "wb") as output:
                            output.write(raw)
                    outputs.append({"order": index, "image_path": str(path), "dimensions": dimensions,
                                    "sha256": digest, "bytes": len(raw)})
                job.update(state="complete", outputs=outputs, output_count=len(outputs), source=source,
                           submitted=True, generated=True,
                           cleanup_status="preserved" if job.get("preserve_chat") or len(outputs) > 1 else "pending" if cleanup_pending else "not_requested",
                           quality_note="Rendered asset; original download resolution not verified.")
                if len(outputs) == 1:
                    job.update({key: outputs[0][key] for key in ("image_path", "dimensions", "sha256")})
                if chat_path is not None:
                    job["chat_path"] = chat_path
            if prompt_binding is not None:
                job["prompt_binding"] = dict(prompt_binding)
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

    def _receipt(self, job: dict, *, wait_timed_out: bool = False) -> dict:
        output = job.get("outputs")[0] if isinstance(job.get("outputs"), list) and job.get("outputs") else {}
        receipt = {"job_id": job["job_id"], "state": job["state"],
                   "image_path": job.get("image_path"), "dimensions": job.get("dimensions"),
                   "sha256": job.get("sha256"), "bytes": output.get("bytes"),
                   "cleanup_status": job.get("cleanup_status"), "error": job.get("error"),
                   "submitted": job.get("submitted"), "generated": job.get("generated"),
                   "wait_timed_out": wait_timed_out}
        copied = short_outputs(job)
        if copied:
            receipt["outputs"] = copied
            receipt["output_count"] = len(copied)
        if job.get("cleanup_confirmation"):
            receipt["cleanup_confirmation"] = job.get("cleanup_confirmation")
        return receipt

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
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._receipt(job, wait_timed_out=True)
                self.finished.wait(remaining)

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
                        "next_action": self._next_action(),
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
                clear_failed_uploads: bool = False, native_upload_names: list[str] | None = None,
                recover_outputs: bool = False, recovery_chat_path: str | None = None) -> dict:
        """Explicit operator action after inspecting the upstream conversation."""
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("unknown job")
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
                resume = (job.get("collect_only") is True and
                          job.get("error") == "Existing submitted-job recovery failed. Existing conversation does not match this job's prompt; image was not collected" and
                          job.get("recovered_from_error", "").startswith("Submission attempted. Multiple images returned;"))
                if (job["state"] != "failed" or job.get("preflight_only") or
                        (job.get("collect_only") and not resume) or
                        (not resume and not job.get("error", "").startswith("Submission attempted. Multiple images returned;"))):
                    raise ValueError("only the inspected submitted multiple-image failure can be recovered once")
                if (not self.client or time.monotonic() - self.client["seen"] > 90 or
                        self.client["client_id"] != job["client_id"] or self.client.get("worker_version") not in OUTPUT_BINDING_REVISIONS):
                    raise ValueError("original online extension 0.1.20 or a supported newer matcher is required")
                revision = OUTPUT_BINDING_REVISIONS[self.client["worker_version"]]
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
                previous_error = job.pop("error")
                job.update(state="queued", collect_only=True, preserve_chat=True, recovery_chat_path=recovery_chat_path,
                           recovery_dom=dict(inspected), output_binding_revision=revision)
                if resume:
                    job.update(output_recovery_resumed=True, previous_recovery_error=previous_error)
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
                elif self.path == "/agent/wait":
                    result = queue.wait_for_job(data["job_id"], data.get("timeout_seconds", 120))
                elif self.path == "/agent/image":
                    result = queue.submit(**data)
                elif self.path == "/agent/confirm-delete":
                    result = queue.confirm_delete(**data)
                elif self.path == "/agent/resolve":
                    if data.get("inspected_chatgpt") is not True:
                        raise ValueError("inspect ChatGPT before resolving uncertain work")
                    result = queue.resolve(data["job_id"], data.get("clear_preflight_uploads", False),
                                           data.get("clear_failed_uploads", False), data.get("native_upload_names"),
                                           data.get("recover_outputs", False), data.get("recovery_chat_path"))
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


def compact_status(raw: dict) -> dict:
    """Short MCP receipt. Drops prompts, diagnostics, and job history."""
    if not isinstance(raw, dict):
        raise ValueError("invalid status")
    if "job_id" in raw or "state" in raw:
        output = raw.get("outputs")[0] if isinstance(raw.get("outputs"), list) and raw.get("outputs") else {}
        receipt = {"job_id": raw.get("job_id"), "state": raw.get("state"),
                   "image_path": raw.get("image_path"), "dimensions": raw.get("dimensions"),
                   "sha256": raw.get("sha256"),
                   "bytes": output.get("bytes") if isinstance(output, dict) else raw.get("bytes"),
                   "cleanup_status": raw.get("cleanup_status"), "error": raw.get("error"),
                   "wait_timed_out": raw.get("wait_timed_out", False)}
        copied = short_outputs(raw)
        if copied:
            receipt["outputs"] = copied
            receipt["output_count"] = len(copied)
        if raw.get("cleanup_confirmation"):
            receipt["cleanup_confirmation"] = raw.get("cleanup_confirmation")
        return receipt
    brief = {"account": raw.get("account"), "paired": raw.get("paired"),
             "extension_online": raw.get("extension_online"), "next_action": raw.get("next_action")}
    jobs = raw.get("jobs") if isinstance(raw.get("jobs"), list) else []
    open_job = next((job for job in jobs if isinstance(job, dict) and job_occupies_tab(job)), None)
    if open_job:
        brief.update(job_id=open_job.get("job_id"), state=open_job.get("state"),
                     cleanup_status=open_job.get("cleanup_status"))
    return brief


def create_mcp(queue):
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("gpt-bridge", instructions="Generate or edit one ChatGPT image on this machine. Call status, then generate or edit once, then wait. Open image_path. Do not send the job again.")

    @server.tool()
    def status(job_id: str = "") -> dict:
        """Paired tab, or one job. Returns account, paired, extension_online, next_action. With job_id, returns state and image_path."""
        return compact_status(queue.status(job_id))

    @server.tool()
    def wait(job_id: str, timeout_seconds: int = 120) -> dict:
        """Wait until the image is saved and cleanup has finished, or the job has failed. Returns image_path and every output. If wait_timed_out is true, or cleanup_status is pending or confirmation_required, call wait again. Do not generate or resolve."""
        return queue.wait_for_job(job_id, timeout_seconds)

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
            return compact_status(queue.resolve(job_id, clear_preflight_uploads, clear_failed_uploads, native_upload_names, recover_outputs, recovery_chat_path))
        if clear_failed_uploads or native_upload_names is not None:
            return compact_status(queue.resolve(job_id, clear_preflight_uploads, clear_failed_uploads, native_upload_names))
        return compact_status(queue.resolve(job_id, clear_preflight_uploads))

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
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument("--connect", action="store_true",
                           help="Share an already running local extension worker; do not create another queue or listener")
    lifecycle.add_argument("--serve", action="store_true",
                           help="Run only the loopback worker, independent of MCP stdio; agent hosts use --connect")
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
