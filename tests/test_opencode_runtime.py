import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from chatgpt_api.integration_installer import install_opencode


pytestmark = pytest.mark.skipif(
    os.environ.get("GPT_BRIDGE_RUN_OPENCODE_RUNTIME_TESTS") != "1" or shutil.which("opencode") is None,
    reason="set GPT_BRIDGE_RUN_OPENCODE_RUNTIME_TESTS=1 with OpenCode installed",
)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_installed_opencode_tools_are_registered_by_the_runtime(tmp_path):
    config_home = tmp_path / "config"
    config_dir = config_home / "opencode"
    result = install_opencode(
        scope="user",
        home=tmp_path,
        environ={"XDG_CONFIG_HOME": str(config_home)},
    )
    assert result.ok is True

    port = _free_port()
    environment = dict(os.environ)
    environment["OPENCODE_CONFIG_DIR"] = str(config_dir)
    process = subprocess.Popen(
        ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        tool_ids = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise AssertionError(f"OpenCode exited before registration check:\n{output}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/experimental/tool/ids",
                    timeout=1,
                ) as response:
                    tool_ids = json.load(response)
                break
            except OSError:
                time.sleep(0.1)
        assert tool_ids is not None
        assert {
            "gpt_bridge_chat",
            "gpt_bridge_doctor",
            "gpt_bridge_image",
            "gpt_bridge_image_edit",
            "gpt_bridge_report",
            "gpt_bridge_research",
        }.issubset(set(tool_ids))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
