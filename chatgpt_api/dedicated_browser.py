"""Run GPT Bridge in its own Chrome process and persistent profile."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - the dedicated browser is currently macOS/Linux only
    fcntl = None

ACCOUNT = "second"
CHATGPT_URL = "https://chatgpt.com/"
MODULE_MARKER = "chatgpt_api.dedicated_browser"


@dataclass(frozen=True)
class BrowserConfig:
    account: str
    chrome: Path
    extension: Path
    state_dir: Path

    @property
    def profile(self) -> Path:
        return self.state_dir / "chrome-profile"

    @property
    def pid_file(self) -> Path:
        return self.state_dir / "browser.json"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "supervisor.lock"


def default_state_dir(account: str = ACCOUNT) -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "gpt-bridge" / "browser" / account


def _chrome_for_testing_candidates(state_dir: Path) -> list[Path]:
    candidates = [Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
                  Path.home() / "Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"]
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        archive_dir = "chrome-mac-arm64" if machine in {"arm64", "aarch64"} else "chrome-mac-x64"
        candidates.append(state_dir / "chrome-for-testing" / archive_dir / "Google Chrome for Testing.app" /
                          "Contents/MacOS/Google Chrome for Testing")
    elif sys.platform.startswith("linux"):
        archive_dir = "chrome-linux-arm64" if machine in {"arm64", "aarch64"} else "chrome-linux64"
        candidates.append(state_dir / "chrome-for-testing" / archive_dir / "chrome")
    return candidates


def find_chrome(explicit: str | None = None, *, state_dir: Path | None = None) -> Path:
    state_dir = state_dir or default_state_dir()
    candidates = [explicit, os.environ.get("GPT_BRIDGE_CHROME"),
                  *(str(path) for path in _chrome_for_testing_candidates(state_dir)),
                  shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("google-chrome"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise FileNotFoundError("Chrome for Testing/Chromium not found; pass --chrome or set GPT_BRIDGE_CHROME")


def ensure_extension_loading_supported(chrome: Path) -> str:
    try:
        result = subprocess.run([str(chrome), "--version"], capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("cannot verify the selected browser; use Chrome for Testing or Chromium") from error
    version = (result.stdout or result.stderr).strip()
    if "Google Chrome for Testing" in version or version.startswith("Chromium "):
        return version
    match = re.search(r"\bGoogle Chrome\s+(\d+)\.", version)
    if match and int(match.group(1)) < 137:
        return version
    if match:
        raise RuntimeError(f"{version} ignores --load-extension; use Chrome for Testing or Chromium for the dedicated profile")
    raise RuntimeError("cannot verify extension loading support; use Chrome for Testing or Chromium for the dedicated profile")


def make_config(args: argparse.Namespace) -> BrowserConfig:
    if args.account != ACCOUNT:
        raise ValueError("the dedicated image browser only supports account 'second'")
    root = Path(__file__).resolve().parent.parent
    extension = Path(args.extension or root / "extensions/chatgpt-image").expanduser().resolve()
    if not (extension / "manifest.json").is_file():
        raise FileNotFoundError(f"GPT Bridge extension not found: {extension}")
    state_dir = Path(args.state_dir or default_state_dir(args.account)).expanduser().resolve()
    return BrowserConfig(args.account, find_chrome(args.chrome, state_dir=state_dir), extension, state_dir)


def chrome_argv(config: BrowserConfig, *, headful: bool) -> list[str]:
    argv = [str(config.chrome), f"--user-data-dir={config.profile}", "--no-first-run",
            "--no-default-browser-check", f"--disable-extensions-except={config.extension}",
            f"--load-extension={config.extension}"]
    if not headful:
        argv += ["--window-position=-32000,-32000", "--window-size=1440,1000"]
    return [*argv, CHATGPT_URL]


def process_command(pid: int) -> str:
    if pid <= 0:
        return ""
    completed = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def read_metadata(config: BrowserConfig) -> dict:
    try:
        value = json.loads(config.pid_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def owned_status(config: BrowserConfig) -> dict:
    meta = read_metadata(config)
    supervisor_pid, chrome_pid = int(meta.get("supervisor_pid") or 0), int(meta.get("chrome_pid") or 0)
    supervisor_command, chrome_command = process_command(supervisor_pid), process_command(chrome_pid)
    mode = meta.get("mode")
    if mode not in {"background", "setup"}:
        mode = None
    command_mode = "setup" if mode == "setup" else "run"
    supervisor_owned = (MODULE_MARKER in supervisor_command and
                        f" {command_mode} " in f" {supervisor_command} " and
                        meta.get("profile") == str(config.profile) and mode is not None)
    chrome_owned = f"--user-data-dir={config.profile}" in chrome_command
    running = supervisor_owned and chrome_owned
    return {"running": running, "mode": meta.get("mode") if running else None,
            "supervisor_pid": supervisor_pid if running else None, "chrome_pid": chrome_pid if running else None,
            "profile": str(config.profile), "extension": str(config.extension)}


def _acquire_lock(config: BrowserConfig):
    if fcntl is None:
        raise RuntimeError("dedicated browser locking requires macOS or Linux")
    config.state_dir.mkdir(parents=True, exist_ok=True)
    handle = config.lock_file.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("dedicated GPT Bridge Chrome is already starting or running") from None
    return handle


def _refuse_foreign_profile_lock(config: BrowserConfig) -> None:
    if os.path.lexists(config.profile / "SingletonLock") and not owned_status(config)["running"]:
        raise RuntimeError(f"Chrome profile is locked by an unowned process: {config.profile}; close it before continuing")


def supervise(config: BrowserConfig, *, headful: bool) -> int:
    ensure_extension_loading_supported(config.chrome)
    lock = _acquire_lock(config)
    child: subprocess.Popen | None = None
    try:
        _refuse_foreign_profile_lock(config)
        config.profile.mkdir(parents=True, exist_ok=True)
        child = subprocess.Popen(chrome_argv(config, headful=headful))
        config.pid_file.write_text(json.dumps({"supervisor_pid": os.getpid(), "chrome_pid": child.pid,
                                               "mode": "setup" if headful else "background",
                                               "profile": str(config.profile)}), encoding="utf-8")

        def stop_child(_signum, _frame):
            if child and child.poll() is None:
                child.terminate()

        signal.signal(signal.SIGTERM, stop_child)
        signal.signal(signal.SIGINT, stop_child)
        return child.wait()
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        try:
            config.pid_file.unlink()
        except FileNotFoundError:
            pass
        lock.close()


def start(config: BrowserConfig) -> dict:
    ensure_extension_loading_supported(config.chrome)
    current = owned_status(config)
    if current["running"]:
        return current
    _refuse_foreign_profile_lock(config)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", MODULE_MARKER, "run", "--account", config.account, "--chrome", str(config.chrome),
               "--extension", str(config.extension), "--state-dir", str(config.state_dir)]
    with (config.state_dir / "browser.log").open("ab") as log:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    for _ in range(50):
        time.sleep(0.1)
        current = owned_status(config)
        if current["running"]:
            return current
    raise RuntimeError(f"dedicated Chrome did not start; inspect {config.state_dir / 'browser.log'}")


def stop(config: BrowserConfig) -> bool:
    current = owned_status(config)
    if not current["running"]:
        return False
    os.kill(int(current["supervisor_pid"]), signal.SIGTERM)
    return True


def install_launch_agent(config: BrowserConfig, destination: Path | None = None) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent installation is available only on macOS")
    ensure_extension_loading_supported(config.chrome)
    destination = destination or Path.home() / "Library/LaunchAgents/org.grunte.gpt-bridge-browser-second.plist"
    destination.parent.mkdir(parents=True, exist_ok=True)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, "-m", MODULE_MARKER, "run", "--account", config.account, "--chrome", str(config.chrome),
            "--extension", str(config.extension), "--state-dir", str(config.state_dir)]
    payload = {"Label": "org.grunte.gpt-bridge-browser-second", "ProgramArguments": args, "RunAtLoad": True,
               "KeepAlive": False, "StandardOutPath": str(config.state_dir / "browser.log"),
               "StandardErrorPath": str(config.state_dir / "browser.log")}
    destination.write_bytes(plistlib.dumps(payload))
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "setup", "run", "status", "stop", "install-launch-agent"])
    parser.add_argument("--account", default=ACCOUNT)
    parser.add_argument("--chrome")
    parser.add_argument("--extension")
    parser.add_argument("--state-dir")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = make_config(args)
        if args.command == "run":
            return supervise(config, headful=False)
        if args.command == "setup":
            if owned_status(config)["running"]:
                raise RuntimeError("stop the background dedicated Chrome before opening setup mode")
            return supervise(config, headful=True)
        if args.command == "start":
            result = start(config)
        elif args.command == "stop":
            result = {**owned_status(config), "stopped": stop(config)}
        elif args.command == "install-launch-agent":
            result = {"installed": str(install_launch_agent(config))}
        else:
            result = owned_status(config)
        print(json.dumps(result) if args.json else result)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"dedicated browser: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
