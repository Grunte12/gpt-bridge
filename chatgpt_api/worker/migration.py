"""Non-destructive import of ``web-chat-bridge-cli`` conversation state."""

from __future__ import annotations

import json
import os
from pathlib import Path

from chatgpt_api.threads import ThreadState, save_thread, validate_thread_name


def default_legacy_threads_dir() -> Path:
    root = os.environ.get("WCBRIDGE_DATA_DIR", "").strip()
    data_dir = Path(root).expanduser() if root else Path.home() / ".web-chat-bridge-cli"
    return data_dir / "threads"


def migrate_legacy_threads(source: Path, destination: Path, *, overwrite: bool = False) -> dict[str, object]:
    """Copy valid legacy JSON-array threads into the versioned local schema.

    No legacy file is changed or deleted.  Existing destination files are kept
    unless the caller explicitly requests ``overwrite``.
    """
    source = source.expanduser()
    destination = destination.expanduser()
    results: list[dict[str, str]] = []
    if not source.exists():
        return {"source": str(source), "destination": str(destination), "results": results}
    for candidate in sorted(source.glob("*.json")):
        try:
            name = validate_thread_name(candidate.stem)
        except ValueError:
            results.append({"name": candidate.stem, "status": "skipped_invalid_name"})
            continue
        target = destination / f"{name}.json"
        if target.exists() and not overwrite:
            results.append({"name": name, "status": "skipped_existing"})
            continue
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            results.append({"name": name, "status": "skipped_invalid_json"})
            continue
        if not isinstance(raw, list):
            results.append({"name": name, "status": "skipped_unsupported_format"})
            continue
        messages: list[dict[str, str]] = []
        system_fragments: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            role, content = item.get("role"), item.get("content")
            if not isinstance(content, str):
                continue
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
            elif role == "system":
                system_fragments.append(content)
        try:
            save_thread(
                destination,
                ThreadState(name=name, compacted_summary="\n\n".join(system_fragments) or None, messages=messages),
            )
        except OSError:
            results.append({"name": name, "status": "failed_write"})
            continue
        results.append({"name": name, "status": "migrated"})
    return {"source": str(source), "destination": str(destination), "results": results}
