"""Conservative lifecycle wrapper for a stack the user already controls."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from chatgpt_api.core.errors import ProviderError


API_SERVICE = "gpt-bridge"


def default_stack_dir() -> Path | None:
    value = os.environ.get("CHATGPT_STACK_DIR") or os.environ.get("WCBRIDGE_STACK_DIR")
    return Path(value).expanduser() if value and value.strip() else None


def compose_args(action: str, *, full: bool = False, follow: bool = False, tail: int | None = None) -> list[str]:
    services = [] if full else [API_SERVICE]
    if action == "up":
        return ["compose", "up", "-d", *services]
    if action == "down":
        return ["compose", "down"]  # deliberately never uses --volumes
    if action == "restart":
        return ["compose", "restart", *services]
    if action == "logs":
        return ["compose", "logs", *( ["-f"] if follow else []), *( ["--tail", str(tail)] if tail is not None else []), *services]
    if action in {"status", "ps"}:
        return ["compose", "ps", "--format", "json"]
    raise ValueError(f"unknown stack action: {action}")


def run_compose(directory: Path, args: list[str], *, follow: bool = False) -> dict[str, object]:
    if not directory.is_dir():
        raise ProviderError(f"stack directory does not exist: {directory}")
    try:
        if follow:
            completed = subprocess.run(["docker", *args], cwd=directory, check=False)
            return {"ok": completed.returncode == 0, "code": completed.returncode, "stdout": "", "stderr": ""}
        completed = subprocess.run(
            ["docker", *args], cwd=directory, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        return {"ok": False, "code": 1, "stdout": "", "stderr": str(exc)}
    return {"ok": completed.returncode == 0, "code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
