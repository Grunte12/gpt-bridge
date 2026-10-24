import json
import signal
from types import SimpleNamespace
from pathlib import Path

import pytest

from chatgpt_api import dedicated_browser as browser


def _config(tmp_path: Path) -> browser.BrowserConfig:
    chrome = tmp_path / "chrome"
    chrome.write_text("#!/bin/sh\nprintf '%s\\n' 'Chromium 155.0.8059.39'\n")
    chrome.chmod(0o755)
    extension = tmp_path / "extension"
    extension.mkdir()
    (extension / "manifest.json").write_text("{}")
    return browser.BrowserConfig("second", chrome, extension, tmp_path / "state")


def test_background_argv_isolated_profile_only_extension_and_no_cdp(tmp_path):
    config = _config(tmp_path)
    argv = browser.chrome_argv(config, headful=False)
    assert "--window-position=-32000,-32000" in argv
    assert "--window-size=1440,1000" in argv
    assert not any(item.startswith("--headless") for item in argv)
    assert f"--user-data-dir={config.profile}" in argv
    assert f"--disable-extensions-except={config.extension}" in argv
    assert f"--load-extension={config.extension}" in argv
    assert not any("remote-debugging" in item for item in argv)
    assert argv[-1] == "https://chatgpt.com/"


def test_setup_argv_uses_same_profile_without_headless(tmp_path):
    config = _config(tmp_path)
    argv = browser.chrome_argv(config, headful=True)
    assert f"--user-data-dir={config.profile}" in argv
    assert not any(item.startswith("--headless") for item in argv)


def test_branded_chrome_137_or_newer_is_rejected_before_start(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(browser.subprocess, "run", lambda *_args, **_kwargs:
                       SimpleNamespace(stdout="Google Chrome 155.0.8059.39", stderr="", returncode=0))
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("must not spawn"))
    with pytest.raises(RuntimeError, match="ignores --load-extension"):
        browser.start(config)


def test_chrome_for_testing_and_pre_137_branded_chrome_are_supported(tmp_path, monkeypatch):
    config = _config(tmp_path)
    for version in ("Google Chrome for Testing 155.0.8059.39", "Chromium 155.0.8059.39",
                    "Google Chrome 136.0.7103.92"):
        monkeypatch.setattr(browser.subprocess, "run", lambda *_args, _version=version, **_kwargs:
                           SimpleNamespace(stdout=_version, stderr="", returncode=0))
        assert browser.ensure_extension_loading_supported(config.chrome) == version


def test_find_chrome_prefers_cached_cft_over_branded_default(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    cft = (state_dir / "chrome-for-testing" / "chrome-mac-arm64" / "Google Chrome for Testing.app" /
           "Contents/MacOS/Google Chrome for Testing")
    cft.parent.mkdir(parents=True)
    cft.touch()
    monkeypatch.setattr(browser.sys, "platform", "darwin")
    monkeypatch.setattr(browser.platform, "machine", lambda: "arm64")
    monkeypatch.delenv("GPT_BRIDGE_CHROME", raising=False)
    monkeypatch.setattr(browser.shutil, "which", lambda _name: None)
    assert browser.find_chrome(state_dir=state_dir) == cft.resolve()


def test_start_returns_existing_owned_process_instead_of_spawning_duplicate(tmp_path, monkeypatch):
    config = _config(tmp_path)
    existing = {"running": True, "supervisor_pid": 10, "chrome_pid": 11, "mode": "background"}
    monkeypatch.setattr(browser, "ensure_extension_loading_supported", lambda _chrome: "Chromium 155.0.8059.39")
    monkeypatch.setattr(browser, "owned_status", lambda _config: existing)
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not spawn"))
    assert browser.start(config) is existing


def test_foreign_profile_lock_blocks_start(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.profile.mkdir(parents=True)
    (config.profile / "SingletonLock").touch()
    monkeypatch.setattr(browser, "owned_status", lambda _config: {"running": False})
    with pytest.raises(RuntimeError, match="unowned process"):
        browser.start(config)


def test_broken_chrome_singleton_symlink_still_blocks_start(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.profile.mkdir(parents=True)
    (config.profile / "SingletonLock").symlink_to("missing-owner")
    monkeypatch.setattr(browser, "owned_status", lambda _config: {"running": False})
    with pytest.raises(RuntimeError, match="unowned process"):
        browser.start(config)


def test_stop_signals_only_verified_supervisor(tmp_path, monkeypatch):
    config = _config(tmp_path)
    calls = []
    monkeypatch.setattr(browser, "owned_status", lambda _config: {"running": True, "supervisor_pid": 31})
    monkeypatch.setattr(browser.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    assert browser.stop(config) is True
    assert calls == [(31, signal.SIGTERM)]


def test_stop_does_nothing_for_unowned_or_stale_metadata(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(browser, "owned_status", lambda _config: {"running": False})
    monkeypatch.setattr(browser.os, "kill", lambda *_args: pytest.fail("must not signal"))
    assert browser.stop(config) is False


def test_owned_status_requires_supervisor_and_exact_profile(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.state_dir.mkdir(parents=True)
    config.pid_file.write_text(json.dumps({"supervisor_pid": 41, "chrome_pid": 42, "mode": "background",
                                           "profile": str(config.profile)}))
    commands = {41: f"python -m {browser.MODULE_MARKER} run --account second",
                42: f"/Applications/Google Chrome --user-data-dir={config.profile}"}
    monkeypatch.setattr(browser, "process_command", commands.get)
    assert browser.owned_status(config)["running"] is True
    commands[42] = "/Applications/Google Chrome --user-data-dir=/personal/profile"
    assert browser.owned_status(config)["running"] is False


def test_setup_is_owned_and_blocks_a_second_mode(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.state_dir.mkdir(parents=True)
    config.pid_file.write_text(json.dumps({"supervisor_pid": 51, "chrome_pid": 52, "mode": "setup",
                                           "profile": str(config.profile)}))
    commands = {51: f"python -m {browser.MODULE_MARKER} setup --account second",
                52: f"/Applications/Google Chrome --user-data-dir={config.profile}"}
    monkeypatch.setattr(browser, "process_command", commands.get)
    assert browser.owned_status(config)["running"] is True


def test_launch_agent_uses_background_run_and_does_not_keep_restarting(tmp_path, monkeypatch):
    config = _config(tmp_path)
    destination = tmp_path / "agent.plist"
    monkeypatch.setattr(browser.sys, "platform", "darwin")
    browser.install_launch_agent(config, destination)
    text = destination.read_text()
    assert browser.MODULE_MARKER in text and "<string>run</string>" in text
    assert "<key>KeepAlive</key>\n\t<false/>" in text
