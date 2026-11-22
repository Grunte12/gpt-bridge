"""Durable, fail-closed batch feeder for the native image queue."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
import threading
import time
import uuid
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def durable_write(path, data, *, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, obj):
    temporary = path.with_name(path.name + ".tmp")
    durable_write(temporary, json.dumps(obj, sort_keys=True).encode())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def real_directory(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_dir() or path.resolve() != path:
        raise ValueError("destination must be an existing absolute directory without symlinks")
    return path


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("source must be a regular non-symlink file")
        return source.read()


def audit_run(root, items):
    """Bind items to the owner's registry and both existing attempt ledgers."""
    registry = json.loads(read_regular(root / "prompts.json"))
    if not isinstance(registry, list):
        raise ValueError("invalid prompt registry")
    prompts = {}
    for row in registry:
        if not isinstance(row, dict) or not isinstance(row.get("scenario_id"), str) or not isinstance(row.get("prompt"), str):
            raise ValueError("invalid prompt registry row")
        sid = row["scenario_id"]
        if sid in prompts:
            raise ValueError("duplicate registry scenario")
        prompts[sid] = row["prompt"]
    ledger = csv.DictReader(io.StringIO(read_regular(root / "generation_log.tsv").decode()), delimiter="\t")
    if not ledger.fieldnames or "scenario_id" not in ledger.fieldnames:
        raise ValueError("invalid generation ledger")
    attempted = set()
    for row in ledger:
        sid = row.get("scenario_id")
        if not sid or sid not in prompts:
            raise ValueError("invalid generation ledger scenario")
        attempted.add(sid)
    marks = real_directory(str(root / "receipts"))
    for marker in marks.glob("*-attempt.json"):
        if marker.is_symlink() or not marker.is_file():
            raise ValueError("invalid attempt marker")
        sid = marker.name[:-len("-attempt.json")]
        if sid not in prompts:
            raise ValueError("unknown attempt marker")
        attempted.add(sid)
    for item in items:
        sid = item["scenario_id"]
        if sid not in prompts or item["prompt"] != prompts[sid]:
            raise ValueError("item differs from approved prompt registry")
        if sid in attempted:
            raise ValueError("scenario already attempted")


def validated_job_image(queue, job):
    root = queue.root / job["job_id"]
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid job directory")
    path = Path(job["image_path"])
    if not path.is_absolute() or path.parent != root or path.suffix.lower() not in {".png", ".jpg", ".webp"}:
        raise ValueError("image outside exact job directory")
    return path, read_regular(path)


class BatchFeeder:
    def __init__(self, queue):
        self.queue = queue
        self.root = queue.root / "batches"
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.batches = {}
        for path in self.root.glob("*.json"):
            try:
                record = json.loads(path.read_text())
                if record.get("state") == "running":
                    record.update(state="stopped", stop_reason="server restarted; inspect reserved work before proceeding")
                    atomic_json(path, record)
                self.batches[record["batch_id"]] = record
            except (ValueError, KeyError, OSError):
                raise ValueError("invalid batch record; refusing to start feeder")
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _save(self, record):
        atomic_json(self.root / (record["batch_id"] + ".json"), record)

    def start(self, batch_id, items, destination, attempts):
        if not isinstance(batch_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", batch_id):
            raise ValueError("invalid batch ID")
        dest, marks = real_directory(destination), real_directory(attempts)
        roots = [root for root in self.queue.batch_allowed_runs if dest == root / "raw" and marks == root / "receipts"]
        if len(roots) != 1:
            raise ValueError("run directories are not explicitly allowed")
        run_root = roots[0]
        if not isinstance(items, list) or not 1 <= len(items) <= 500:
            raise ValueError("invalid batch items")
        frozen, ids, hashes = [], set(), set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {"scenario_id", "prompt", "prompt_sha256"}:
                raise ValueError("invalid batch item")
            sid, prompt, h = item["scenario_id"], item["prompt"], item["prompt_sha256"]
            if not isinstance(sid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,100}", sid):
                raise ValueError("invalid scenario ID")
            if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 16000 or digest(prompt.encode()) != h:
                raise ValueError("prompt hash mismatch")
            if sid in ids or h in hashes:
                raise ValueError("duplicate scenario or prompt")
            ids.add(sid); hashes.add(h)
            frozen.append(dict(item))
        manifest = {"batch_id": batch_id, "items": frozen, "destination": str(dest), "attempts": str(marks)}
        identity = digest(json.dumps(manifest, sort_keys=True).encode())
        with self.queue.lock:
            if batch_id in self.batches:
                record = self.batches[batch_id]
                if record["manifest_hash"] != identity:
                    raise ValueError("batch ID already used with different manifest")
                return self.status(batch_id)
            if any(b["state"] == "running" for b in self.batches.values()):
                raise ValueError("another batch is running")
            if self.queue.halted_job or any(j.get("state") not in {"complete", "failed", "interrupted"} for j in self.queue.jobs.values()):
                raise ValueError("queue is not idle")
            audit_run(run_root, frozen)
            for sid in ids:
                if (marks / (sid + "-attempt.json")).exists() or any(dest.glob(sid + ".*")):
                    raise ValueError("scenario already attempted or output exists")
            record = {**manifest, "manifest_hash": identity, "state": "running", "stop_reason": None,
                      "progress": [{"scenario_id": x["scenario_id"], "state": "untouched"} for x in frozen]}
            self._save(record)
            self.batches[batch_id] = record
            return self.status(batch_id)

    def status(self, batch_id):
        with self.queue.lock:
            if batch_id not in self.batches:
                raise ValueError("unknown batch")
            r = self.batches[batch_id]
            return {k: r[k] for k in ("batch_id", "manifest_hash", "state", "stop_reason", "progress")} | ({"stop_detail": r["stop_detail"]} if "stop_detail" in r else {})

    def _stop(self, record, message):
        status = self.queue.status()
        running = next((p for p in record["progress"] if p["state"] == "reserved"), None)
        job = self.queue.jobs.get(running["job_id"]) if running else None
        error = status.get("tab_error") or ""
        receiver = (status.get("extension_diagnostics") or {}).get("receiver_error")
        allowed_receivers = {"", "unreported", "tab_missing", "wrong_origin", "invalid_reply",
                             "unavailable", "no_receiver", "port_closed", "message_failed"}
        lower = error.lower()
        category = ("none" if not error else "busy" if error == "Content worker already running" else
                    "verification" if any(x in lower for x in ("captcha", "verification")) else
                    "restriction" if any(x in lower for x in ("restriction", "restricted")) else
                    "rate_limit" if "429" in lower or "quota" in lower else
                    "access" if any(x in lower for x in ("403", "sign in", "sign-in", "login")) else
                    "receiver" if error.startswith("Native tab inspection failed:") else "other")
        phase = job.get("phase") if job else "none"
        allowed_phases = {"none", "prepared", "submit_attempted", "remote_started", "result_captured", "completed"}
        detail = {"online": bool(status["extension_online"]), "tab_error_class": category,
                  "receiver_reason": receiver if receiver in allowed_receivers else "other",
                  "owned_job_phase": phase if phase in allowed_phases else "other"}
        record.update(state="stopped", stop_reason=message[:300], stop_detail=detail)
        self._save(record)

    def save_result(self, record, running, job):
        src, raw = validated_job_image(self.queue, job)
        if digest(raw) != job["sha256"]:
            raise ValueError("saved image hash mismatch")
        target = real_directory(record["destination"]) / (running["scenario_id"] + src.suffix)
        durable_write(target, raw, exclusive=True)
        if digest(target.read_bytes()) != job["sha256"]:
            raise ValueError("copied image hash mismatch")
        running.update(state="saved", image_path=str(target), sha256=job["sha256"])
        self._save(record)

    def tick(self, record):
        with self.queue.lock:
            if record["state"] != "running":
                return
            q = self.queue
            if q.halted_job:
                self._stop(record, "queue halted; inspect original job")
                return
            status = q.status()
            running = next((p for p in record["progress"] if p["state"] == "reserved"), None)
            job = q.jobs.get(running["job_id"]) if running else None
            error = status.get("tab_error") or ""
            benign_busy = error == "Content worker already running"
            if not status["extension_online"] or (error and not benign_busy):
                self._stop(record, "paired tab offline or reports an error; inspect before resuming")
                return
            if running:
                if not job:
                    self._stop(record, "reserved job missing; delivery is uncertain")
                    return
                if job["state"] in {"queued", "claimed"}:
                    return
                if job["state"] != "complete" or not job.get("image_path") or not job.get("sha256"):
                    self._stop(record, "job failed or interrupted; inspect before resuming")
                    return
                self.save_result(record, running, job)
            batch_jobs = [j for j in q.jobs.values() if j.get("batch_id") == record["batch_id"]]
            if any(j.get("cleanup_status") == "failed" for j in batch_jobs):
                self._stop(record, "saved-chat cleanup failed; inspect before continuing")
                return
            if any(j.get("cleanup_status") in {"pending", "confirmation_required"} for j in batch_jobs):
                return
            pending = next((p for p in record["progress"] if p["state"] == "untouched"), None)
            if not pending:
                record["state"] = "complete"
                self._save(record)
                return
            if any(j.get("state") not in {"complete", "failed", "interrupted", "waiting_for_batch"} for j in q.jobs.values()):
                return
            if benign_busy or not status["tab_ready"]:
                return  # Wait for a fresh ready heartbeat before reserving another job.
            item = next(x for x in record["items"] if x["scenario_id"] == pending["scenario_id"])
            audit_run(Path(record["destination"]).parent, [item])
            jid = uuid.uuid4().hex
            pending.update(state="reserved", job_id=jid)
            self._save(record)
            marker = real_directory(record["attempts"]) / (pending["scenario_id"] + "-attempt.json")
            durable_write(marker, json.dumps({**item, "state": "attempt_marker_written", "batch_id": record["batch_id"], "job_id": jid}).encode(), exclusive=True)
            q.submit(item["prompt"], "Create image", _batch_job_id=jid, _batch_id=record["batch_id"])

    def _run(self):
        while True:
            time.sleep(1)
            for record in list(self.batches.values()):
                try:
                    self.tick(record)
                except Exception:
                    with self.queue.lock:
                        try:
                            self._stop(record, "batch I/O or queue error; inspect reserved item")
                        except Exception:
                            record.update(state="stopped", stop_reason="batch persistence error; inspect reserved item")
