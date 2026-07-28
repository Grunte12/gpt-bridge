from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from chatgpt_api.integration_installer import install_claude, install_codex


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_HOST_TESTS = os.environ.get("GPT_BRIDGE_RUN_CODEX_CLAUDE_RUNTIME_TESTS") == "1"

EXPECTED_ROUTES = {
    ("worker", "tools"),
    ("worker", "doctor"),
    ("worker", "chat"),
    ("worker", "thread"),
    ("worker", "web", "list"),
    ("worker", "web", "show"),
    ("worker", "web", "pull"),
    ("worker", "web", "send"),
    ("worker", "web", "delete"),
    ("worker", "report"),
    ("worker", "image"),
    ("worker", "edit"),
    ("worker", "research"),
}

FAKE_BRIDGE = r"""#!/usr/bin/env python3
import base64
import json
import os
import pathlib
import sys

args = sys.argv[1:]
with open(os.environ["GPT_BRIDGE_HOST_TEST_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")

def value(flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default

if args[:2] == ["worker", "tools"]:
    query = value("--query")
    if query:
        out = {
            "object": "chatgpt.worker.capability.search",
            "query": query,
            "matches": [{
                "id": "technical-diagram",
                "summary": "Generate a technical diagram.",
                "references": ["references/image-core.md", "references/technical-diagram.md"],
            }],
            "hint": "Read only returned references.",
        }
    else:
        out = {"object": "chatgpt.worker.capabilities", "capabilities": []}
elif args[:2] == ["worker", "doctor"]:
    out = {"object": "chatgpt.worker.doctor", "ok": True}
elif args[:2] == ["worker", "chat"]:
    out = {"object": "chat.completion", "choices": [{"message": {"content": "fixture chat"}}]}
elif args[:3] == ["worker", "thread", "clear"]:
    out = {"object": "chatgpt.worker.thread", "cleared": True}
elif args[:3] == ["worker", "web", "list"]:
    out = {"object": "chatgpt.web.conversation.list", "conversations": [{
        "id": "12345678-abcd-4321-abcd-1234567890ab", "title": "Host contract fixture",
        "web_url": "https://chatgpt.com/c/12345678-abcd-4321-abcd-1234567890ab",
    }]}
elif args[:3] == ["worker", "web", "show"]:
    target = value("--output")
    if target:
        pathlib.Path(target).write_text("# Fixture conversation\n", encoding="utf-8")
    out = {"object": "chatgpt.web.conversation", "id": "12345678-abcd-4321-abcd-1234567890ab", "path": target}
elif args[:3] == ["worker", "web", "pull"]:
    target = value("--output-path")
    pathlib.Path(target).write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAHnOcQAAAAABJRU5ErkJggg=="
    ))
    out = {"object": "chatgpt.web.conversation.assets", "assets": [{"path": target}]}
elif args[:3] == ["worker", "web", "send"]:
    out = {"object": "chatgpt.web.conversation.turn", "text": "fixture continuation"}
elif args[:3] == ["worker", "web", "delete"]:
    out = {"object": "chatgpt.web.conversation.delete", "id": "12345678-abcd-4321-abcd-1234567890ab", "ok": True, "soft_deleted": True}
elif args[:2] == ["worker", "report"]:
    target = value("--out")
    pathlib.Path(target).write_text("<!doctype html><title>Fixture</title>\n", encoding="utf-8")
    out = {"object": "chatgpt.worker.report", "path": target}
elif args[:2] in (["worker", "image"], ["worker", "edit"]):
    target = value("--output-path")
    pathlib.Path(target).write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAHnOcQAAAAABJRU5ErkJggg=="
    ))
    out = {"ok": True, "outputs": [{"path": target}], "session_cleanup": "soft_deleted"}
elif args[:2] == ["worker", "research"]:
    out = {"object": "chatgpt.research", "status": "completed", "text": "fixture research"}
else:
    out = {"ok": True, "args": args}
print(json.dumps(out))
"""


PROMPTS = (
    """Use the gpt-bridge-worker skill and Bash only. This is a local fixture; call no real network service.
The test passes only when every exact gpt-bridge command is executed. Do not substitute, simulate, or create outputs yourself.
Run these commands exactly once in order:
./bin/gpt-bridge worker tools --query "technical architecture diagram" --json
./bin/gpt-bridge worker doctor --json
./bin/gpt-bridge worker chat --message "fixture" --json
./bin/gpt-bridge worker chat --message "fixture thread" --thread host-test --json
./bin/gpt-bridge worker thread clear host-test --json
Return only a short completion statement.""",
    """Use the gpt-bridge-worker skill and Bash only. This is a local fixture; call no real network service.
The test passes only when every exact gpt-bridge command is executed. Do not substitute, simulate, or create outputs yourself.
Run these commands exactly once in order:
./bin/gpt-bridge worker web list --query "Host contract fixture" --json
./bin/gpt-bridge worker web show --conversation 12345678-abcd-4321-abcd-1234567890ab --output context.md --json
./bin/gpt-bridge worker web pull --conversation 12345678-abcd-4321-abcd-1234567890ab --output-path pulled.png --json
./bin/gpt-bridge worker web send --conversation 12345678-abcd-4321-abcd-1234567890ab --message "fixture continuation" --json
./bin/gpt-bridge worker web delete --conversation 12345678-abcd-4321-abcd-1234567890ab --yes --json
Return only a short completion statement.""",
    """Use the gpt-bridge-worker skill and Bash only. This is a local fixture; call no real network service.
The test passes only when the exact gpt-bridge command is executed. Do not author the report or create the file yourself.
Run this command exactly once:
./bin/gpt-bridge worker report --prompt "fixture report" --out report.html --json
Return only a short completion statement.""",
    """Use the gpt-bridge-worker skill and Bash only. This is a local fixture; call no real network service.
The test passes only when every exact gpt-bridge command is executed. Do not substitute, simulate, or create outputs yourself.
Run these commands exactly once in order:
./bin/gpt-bridge worker image --prompt "fixture image" --output-path image.png --cleanup-session --brief
./bin/gpt-bridge worker edit --prompt "fixture edit" --input-image image.png --output-path edited.png --cleanup-session --brief
./bin/gpt-bridge worker research --prompt "fixture research" --json
Return only a short completion statement.""",
)


def _route_prefix(args: list[str]) -> tuple[str, ...]:
    if args[:2] == ["worker", "web"]:
        return tuple(args[:3])
    if args[:2] == ["worker", "thread"]:
        return tuple(args[:2])
    return tuple(args[:2])


def _run_host(
    host: str,
    workspace: Path,
    environment: dict[str, str],
    prompt: str,
) -> subprocess.CompletedProcess[str]:
    if host == "codex":
        command = [
            shutil.which("codex") or "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "danger-full-access",
            "--config",
            'model_reasoning_effort="low"',
            "--cd",
            str(workspace),
            prompt,
        ]
    else:
        command = [
            shutil.which("claude") or "claude",
            "--print",
            "--no-session-persistence",
            "--permission-mode",
            "bypassPermissions",
            "--effort",
            "low",
            "--allowedTools=Bash,Read",
            "--",
            prompt,
        ]
    return subprocess.run(
        command,
        cwd=workspace,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.skipif(not RUN_HOST_TESTS, reason="set GPT_BRIDGE_RUN_CODEX_CLAUDE_RUNTIME_TESTS=1")
@pytest.mark.parametrize("host", ["codex", "claude"])
def test_real_host_loads_skill_and_routes_every_capability_to_cli(host, tmp_path):
    if shutil.which(host) is None:
        pytest.skip(f"{host} is not installed")
    workspace = tmp_path / host
    workspace.mkdir()
    if host == "codex":
        result = install_codex(str(REPO_ROOT), scope="project", project_dir=workspace)
    else:
        result = install_claude(str(REPO_ROOT), scope="project", project_dir=workspace)
    assert result.ok

    binary_dir = workspace / "bin"
    binary_dir.mkdir()
    bridge = binary_dir / "gpt-bridge"
    bridge.write_text(FAKE_BRIDGE, encoding="utf-8")
    bridge.chmod(0o755)
    log_path = workspace / "calls.jsonl"
    environment = dict(os.environ)
    environment["PATH"] = f"{binary_dir}{os.pathsep}{environment['PATH']}"
    environment["GPT_BRIDGE_HOST_TEST_LOG"] = str(log_path)

    for prompt in PROMPTS:
        completed = _run_host(host, workspace, environment, prompt)
        assert completed.returncode == 0, completed.stderr or completed.stdout
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    routes = {_route_prefix(call) for call in calls}
    assert EXPECTED_ROUTES <= routes
    assert any(call[:2] == ["worker", "image"] and "--cleanup-session" in call for call in calls)
    assert any(call[:2] == ["worker", "edit"] and "--cleanup-session" in call for call in calls)
    assert any(call[:3] == ["worker", "web", "delete"] and "--yes" in call for call in calls)
