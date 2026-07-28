#!/usr/bin/env python3
"""Bootstrap GPT Bridge and its Codex, Claude Code, and OpenCode adapters."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

if sys.version_info < (3, 11):
    raise SystemExit("GPT Bridge requires Python 3.11 or newer; rerun this script with that interpreter.")

from chatgpt_api.integration_installer import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(repo_root=REPO_ROOT))
