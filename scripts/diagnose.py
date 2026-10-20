#!/usr/bin/env python3
"""Read-only health check for the GPT Bridge extension worker.

Usage (from the repo root):
  .venv/bin/python scripts/diagnose.py                 # one snapshot
  .venv/bin/python scripts/diagnose.py --job <job_id>  # also show that job
  .venv/bin/python scripts/diagnose.py --watch 60      # repeat every 5 s for 60 s
  .venv/bin/python scripts/diagnose.py --json          # raw snapshot for scripts

It only calls the worker's /agent/status. It never submits, resolves or deletes. The live page report
(result_dom) comes from the paired ChatGPT tab, so it shows what the detector sees right now.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chatgpt_api.extension_bridge import ExtensionClient, read_token  # noqa: E402

DATA_DIR = Path.home() / ".local/share/gpt-bridge/extension/second"
TIMEOUT_DOM = " DOM: "  # content.js appends the page report to its timeout error after this marker.


def page_note(dom: dict) -> str:
    if dom.get("busy"):
        return "page shows the Stop button: ChatGPT is still generating (slow, not stuck)"
    if dom.get("assistant_images", 0) > 0:
        return "page shows an output image and is idle: a running content loop captures it within about 10 s"
    if dom.get("conversation_images", 0) > 0:
        return "page has images but none inside the assistant message: the detector selector misses them"
    return "page shows no output image and no Stop button: no image yet, or generation ended without one"


def timeout_dom(job: dict) -> dict | None:
    """The page report saved in a timeout error; None when absent or cut by the 500-char error limit."""
    error = job.get("error") or ""
    if "Timed out" not in error or TIMEOUT_DOM not in error:
        return None
    try:
        dom = json.loads(error.split(TIMEOUT_DOM, 1)[1])
    except ValueError:
        return None
    return dom if isinstance(dom, dict) else None


def verdict(snapshot: dict, job: dict | None) -> list[str]:
    """Plain-language findings from the numbers; each names the evidence it uses."""
    notes = []
    diag = snapshot.get("extension_diagnostics") or {}
    dom = diag.get("result_dom") or {}
    if not snapshot.get("extension_online"):
        notes.append("extension offline: no heartbeat in 90 s (reload the extension or open a chatgpt.com tab)")
    if snapshot.get("line_halted"):
        notes.append(f"queue halted by job {snapshot['line_halted']}: inspect ChatGPT, then resolve(job_id, inspected_chatgpt=true)")
    # The worker counts chatgpt.com tabs only while searching for a lost paired tab, so 0 alone means nothing.
    if diag.get("content_receiver") == "tab_missing" and not diag.get("chatgpt_tabs"):
        notes.append("paired tab missing and no chatgpt.com tab found: run scripts/ensure-chatgpt-tab.sh")
    if snapshot.get("tab_error"):
        notes.append(f"tab_error reported by the worker: {snapshot['tab_error']}")
    installed, running = snapshot.get("installed_extension_version"), diag.get("worker_version")
    if installed and running and installed != running:
        notes.append(f"version mismatch: repo {installed}, Chrome runs {running}: reload the extension")
    if job and job.get("state") == "claimed" and job.get("phase") == "remote_started" and dom:
        notes.append(page_note(dom))
    if job and (saved := timeout_dom(job)) is not None:
        notes.append("at timeout: " + page_note(saved))
        if dom.get("assistant_images", 0) > 0 and dom.get("chat_path") and dom.get("chat_path") == job.get("chat_path"):
            notes.append("that job's chat shows an output image now: inspect ChatGPT before any resolve; do not resubmit")
    return notes or ["no problem found in the numbers"]


def snapshot_once(client: ExtensionClient, job_id: str | None) -> dict:
    status = client.call("status", {})
    # Without --job, watch the newest claimed job from the status list (state and phase only).
    job = client.call("status", {"job_id": job_id}) if job_id else next(
        (item for item in reversed(status.get("jobs") or []) if item.get("state") == "claimed"), None)
    return {"at": time.strftime("%H:%M:%S"), "status": status, "job": job, "findings": verdict(status, job)}


def render(snap: dict) -> str:
    status, job = snap["status"], snap["job"]
    diag = status.get("extension_diagnostics") or {}
    lines = [f"[{snap['at']}] online={status.get('extension_online')} next_action={status.get('next_action')} "
             f"queue_depth={status.get('queue_depth')} halted={status.get('line_halted')}",
             f"  extension: repo {status.get('installed_extension_version')} / Chrome {diag.get('worker_version')}, "
             f"receiver={diag.get('content_receiver')}, tab_error={status.get('tab_error') or '-'}",
             f"  page now: {json.dumps(diag.get('result_dom'))}"]
    for item in (status.get("jobs") or [])[-5:]:
        lines.append(f"  job {item.get('job_id', '')[:8]} {item.get('state')}/{item.get('phase')} chat={item.get('chat_path') or '-'}")
    if job:
        lines.append(f"  watched job {job.get('job_id', '')[:8]}: {job.get('state')}/{job.get('phase')} error={job.get('error')}")
    lines += [f"  finding: {note}" for note in snap["findings"]]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job")
    parser.add_argument("--watch", type=int, default=0, help="seconds to keep polling every 5 s")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        client = ExtensionClient(read_token(DATA_DIR))
    except (OSError, ValueError) as error:
        # Name only the error type: the token itself is never printed.
        print(f"cannot read the pairing token in {DATA_DIR}: {type(error).__name__}", file=sys.stderr)
        return 2
    end = time.monotonic() + args.watch
    while True:
        try:
            snap = snapshot_once(client, args.job)
            print(json.dumps(snap) if args.json else render(snap), flush=True)
            code = 0
        except ValueError as error:
            # ExtensionClient reports every transport or HTTP failure as ValueError, so an offline worker lands here.
            print(f"[{time.strftime('%H:%M:%S')}] worker unreachable or request rejected: {error}", file=sys.stderr, flush=True)
            code = 1
        if time.monotonic() >= end:
            return code
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
