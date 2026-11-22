"""Retention for bridge-owned image copies. Callers keep their own copy; the bridge copy is temporary."""
from __future__ import annotations

import os
import time
from pathlib import Path

OUTPUT_TTL_DAYS_DEFAULT = 7.0
OUTPUT_TTL_ENV = "GPT_BRIDGE_OUTPUT_TTL_DAYS"
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def ttl_seconds(days: float | str | None = None) -> float:
    """Days -> seconds. None reads GPT_BRIDGE_OUTPUT_TTL_DAYS (default 7). 0 keeps files forever."""
    if days is None:
        days = os.environ.get(OUTPUT_TTL_ENV, "").strip() or OUTPUT_TTL_DAYS_DEFAULT
    value = float(days)
    if value != value or value < 0:
        raise ValueError("output TTL days must be 0 or more")
    return value * 86400


def iso_utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def prune_old_files(directory: Path, max_age_seconds: float, *, now: float | None = None,
                    suffixes=IMAGE_SUFFIXES) -> int:
    """Delete regular image files directly inside directory older than max_age_seconds. 0 disables.
    Never follows symlinks or enters subfolders. Returns the number of files deleted."""
    if not max_age_seconds or directory.is_symlink() or not directory.is_dir():
        return 0
    now = time.time() if now is None else now
    removed = 0
    for entry in os.scandir(directory):
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            continue
        if Path(entry.name).suffix.lower() not in suffixes:
            continue
        try:
            if now - entry.stat(follow_symlinks=False).st_mtime >= max_age_seconds:
                os.unlink(entry.path)
                removed += 1
        except FileNotFoundError:
            continue
    return removed
