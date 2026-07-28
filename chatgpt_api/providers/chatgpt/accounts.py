"""Local ChatGPT account profile helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ACCOUNTS_DIR = Path("secrets/accounts")
DEFAULT_CAPTURE_NAME = "chatgpt-request.txt"
DEFAULT_SETTINGS_NAME = "settings.json"
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
ACCOUNT_NAME_RULE = "account names may only contain English letters, numbers, underscore, and dash"


@dataclass(frozen=True, slots=True)
class ChatGPTAccountProfile:
    name: str
    capture_path: Path

    @property
    def exists(self) -> bool:
        return self.capture_path.exists()

    @property
    def settings_path(self) -> Path:
        return self.capture_path.with_name(DEFAULT_SETTINGS_NAME)

    @property
    def has_settings(self) -> bool:
        return self.settings_path.exists()


def default_accounts_dir() -> Path:
    """Return a stable per-user account store without creating it."""
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "gpt-bridge" / "accounts"
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "gpt-bridge" / "accounts"


def accounts_dir_from_env() -> Path:
    value = os.environ.get("CHATGPT_ACCOUNTS_DIR", "").strip()
    if value:
        return Path(value).expanduser()
    return default_accounts_dir()


def resolve_account_capture_path(account: str, accounts_dir: Path | None = None) -> Path:
    if not _ACCOUNT_RE.fullmatch(account):
        raise ValueError(ACCOUNT_NAME_RULE)
    root = accounts_dir if accounts_dir is not None else accounts_dir_from_env()
    return root.expanduser() / account / DEFAULT_CAPTURE_NAME


def resolve_account_settings_path(account: str, accounts_dir: Path | None = None) -> Path:
    if not _ACCOUNT_RE.fullmatch(account):
        raise ValueError(ACCOUNT_NAME_RULE)
    root = accounts_dir if accounts_dir is not None else accounts_dir_from_env()
    return root.expanduser() / account / DEFAULT_SETTINGS_NAME


def list_account_profiles(accounts_dir: Path | None = None) -> list[ChatGPTAccountProfile]:
    root = accounts_dir if accounts_dir is not None else accounts_dir_from_env()
    root = root.expanduser()
    if not root.exists():
        return []
    profiles: list[ChatGPTAccountProfile] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.is_dir() and _ACCOUNT_RE.fullmatch(child.name):
            profiles.append(ChatGPTAccountProfile(child.name, child / DEFAULT_CAPTURE_NAME))
    return profiles
