"""Local, opt-in conversation state for automation-oriented CLI calls."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


THREAD_SCHEMA_VERSION = 1
_THREAD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(slots=True)
class ThreadState:
    name: str
    compacted_summary: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)


def default_threads_dir() -> Path:
    value = os.environ.get("CHATGPT_THREADS_DIR", "").strip()
    return Path(value).expanduser() if value else Path("outputs/chatgpt-threads")


def validate_thread_name(name: str) -> str:
    normalized = name.strip()
    if not _THREAD_NAME_RE.fullmatch(normalized):
        raise ValueError("thread names may only contain English letters, numbers, underscore, and dash")
    return normalized


def thread_path(directory: Path, name: str) -> Path:
    return directory.expanduser() / f"{validate_thread_name(name)}.json"


def load_thread(directory: Path, name: str) -> ThreadState:
    normalized = validate_thread_name(name)
    path = thread_path(directory, normalized)
    if not path.exists():
        return ThreadState(name=normalized)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"thread file is unreadable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != THREAD_SCHEMA_VERSION:
        raise ValueError(f"thread file has an unsupported format: {path}")
    summary = payload.get("compacted_summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError(f"thread file has an invalid compacted_summary: {path}")
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError(f"thread file has invalid messages: {path}")
    messages: list[dict[str, str]] = []
    for message in raw_messages:
        if not isinstance(message, dict):
            raise ValueError(f"thread file has an invalid message: {path}")
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise ValueError(f"thread file has an invalid message: {path}")
        messages.append({"role": role, "content": content})
    return ThreadState(name=normalized, compacted_summary=summary, messages=messages)


def save_thread(directory: Path, state: ThreadState) -> Path:
    directory = directory.expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    path = thread_path(directory, state.name)
    payload = {
        "version": THREAD_SCHEMA_VERSION,
        "name": state.name,
        "compacted_summary": state.compacted_summary,
        "messages": state.messages,
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def requires_compaction(state: ThreadState, window: int) -> bool:
    return len(state.messages) > window * 2


def compacted_thread(state: ThreadState, summary: str, window: int) -> ThreadState:
    return ThreadState(name=state.name, compacted_summary=summary, messages=state.messages[-window:])


@contextmanager
def lock_thread(directory: Path, name: str) -> Iterator[None]:
    """Prevent two CLI processes from overwriting one named thread."""
    directory = directory.expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = thread_path(directory, name).with_suffix(".lock")
    token = uuid.uuid4().hex
    encoded = json.dumps({"pid": os.getpid(), "created_at": time.time(), "token": token}).encode("utf-8")
    try:
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise ValueError(f"thread is already in use: {validate_thread_name(name)}") from exc
    try:
        with os.fdopen(descriptor, "wb") as lock_file:
            lock_file.write(encoded)
        yield
    finally:
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        if current.get("token") == token:
            lock_path.unlink(missing_ok=True)
