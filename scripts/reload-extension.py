#!/usr/bin/env python3
"""Reload the Chrome extension without touching Chrome's UI.

Usage (from the repo root):
  .venv/bin/python scripts/reload-extension.py            # ask, then wait until the worker takes the order
  .venv/bin/python scripts/reload-extension.py --no-wait  # only ask

It asks the local worker for a one-shot reload. The extension takes the order at its next idle heartbeat (about every
30 s, never while a job holds the tab) and calls chrome.runtime.reload(). The script can confirm that the order was
delivered. It confirms the reload itself only when Chrome ran an older version than the repo and now reports the repo
version. Needs a worker that has the /agent/reload route: after changing chatgpt_api/extension_bridge.py restart it
first (launchctl kickstart -k gui/$UID/org.grunte.gpt-bridge-extension). It never submits, resolves or deletes anything.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chatgpt_api.extension_bridge import ExtensionClient, read_token  # noqa: E402

DATA_DIR = Path.home() / ".local/share/gpt-bridge/extension/second"
OLD_WORKER = "the running worker has no reload route: restart it with the current code, then run this again"


def worker_version(status: dict):
    return (status.get("extension_diagnostics") or {}).get("worker_version")


def reload_and_wait(client, wait_seconds: int = 90, poll=time.sleep, now=time.monotonic) -> tuple[int, str]:
    """Return (exit code, message). 0 = order requested (no wait), delivered, or reload confirmed by version."""
    before = client.call("status", {})
    installed, running = before.get("installed_extension_version"), worker_version(before)
    try:
        client.call("reload", {})
    except ValueError as error:
        return 1, OLD_WORKER if str(error) == "unknown route" else str(error)
    if wait_seconds <= 0:
        return 0, "reload requested; the extension takes it at its next idle heartbeat (about 30 s)"
    outdated = bool(installed and running and running != installed)
    end, status = now() + wait_seconds, before
    while now() < end:
        poll(3)
        status = client.call("status", {})
        if outdated and worker_version(status) == installed:
            return 0, f"reloaded: Chrome now runs {installed} (was {running})"
        if not outdated and not status.get("reload_requested"):
            return 0, (f"the extension took the reload order (worker {worker_version(status)}); "
                       "Chrome's reload is not confirmed because the version did not change")
    if status.get("reload_requested"):
        held = " (a job holds the tab; it reloads after the job)" if status.get("next_action") == "wait" else ""
        return 1, f"reload still pending after {wait_seconds} s{held}; next_action={status.get('next_action')}"
    return 1, f"order delivered but Chrome still reports {worker_version(status)}, repo {installed}; run scripts/diagnose.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--wait", type=int, default=90)
    args = parser.parse_args()
    try:
        client = ExtensionClient(read_token(DATA_DIR))
        code, message = reload_and_wait(client, 0 if args.no_wait else args.wait)
    except (ValueError, OSError) as error:  # Bounded worker or file messages; neither carries the token.
        print(f"cannot reach the worker: {error}", file=sys.stderr)
        return 2
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
