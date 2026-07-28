from pathlib import Path

import pytest

from chatgpt_api.providers.chatgpt.accounts import (
    accounts_dir_from_env,
    default_accounts_dir,
    list_account_profiles,
    resolve_account_capture_path,
)


def test_resolve_account_capture_path():
    assert resolve_account_capture_path("pro", Path("secrets/accounts")) == Path(
        "secrets/accounts/pro/chatgpt-request.txt"
    )


def test_default_accounts_dir_is_stable_and_user_scoped(monkeypatch, tmp_path):
    monkeypatch.delenv("CHATGPT_ACCOUNTS_DIR", raising=False)
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    expected = config_home / "gpt-bridge" / "accounts"
    assert default_accounts_dir() == expected
    assert accounts_dir_from_env() == expected


def test_accounts_dir_environment_override_wins(monkeypatch, tmp_path):
    configured = tmp_path / "custom-accounts"
    monkeypatch.setenv("CHATGPT_ACCOUNTS_DIR", str(configured))

    assert accounts_dir_from_env() == configured


def test_resolve_account_rejects_path_traversal():
    with pytest.raises(ValueError):
        resolve_account_capture_path("../pro", Path("secrets/accounts"))


def test_resolve_account_rejects_non_slug_names():
    for account in ["โปร", "pro.account", "pro account", "-pro"]:
        with pytest.raises(ValueError):
            resolve_account_capture_path(account, Path("secrets/accounts"))


def test_list_account_profiles(tmp_path):
    (tmp_path / "free").mkdir()
    (tmp_path / "pro").mkdir()
    (tmp_path / "โปร").mkdir()
    (tmp_path / "pro.account").mkdir()
    (tmp_path / "pro" / "chatgpt-request.txt").write_text("URL: https://chatgpt.com\n", encoding="utf-8")

    profiles = list_account_profiles(tmp_path)

    assert [profile.name for profile in profiles] == ["free", "pro"]
    assert profiles[0].exists is False
    assert profiles[1].exists is True
