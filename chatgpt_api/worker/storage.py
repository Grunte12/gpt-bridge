"""Locations for worker-owned, non-secret local data."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def default_worker_data_dir() -> Path:
    """Return the platform-appropriate worker data root without creating it."""
    configured = os.environ.get("CHATGPT_WORKER_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "gpt-bridge" / "worker"
    return Path.home() / ".local" / "share" / "gpt-bridge" / "worker"


@dataclass(frozen=True, slots=True)
class WorkerPaths:
    root: Path

    @classmethod
    def default(cls) -> "WorkerPaths":
        return cls(default_worker_data_dir())

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def threads(self) -> Path:
        return self.root / "threads"
