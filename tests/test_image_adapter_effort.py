"""Static/offline checks for image effort controls in consumer adapters."""

import re
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from chatgpt_api.mcp_gateway import CATALOG, Gateway


@pytest.mark.parametrize("tool_name", ["bridge.image", "bridge.edit"])
def test_mcp_image_tools_accept_model_effort_and_image_level(tool_name):
    from jsonschema import validate

    spec = CATALOG[tool_name][1]
    properties = spec["properties"]
    assert {"model", "thinking_effort", "level"} <= properties.keys()
    arguments = {
        "prompt": "make an icon",
        "model": "gpt-6-thinking",
        "thinking_effort": "extended",
        "level": "high",
    }
    if tool_name == "bridge.edit":
        arguments["input_images"] = ["reference.png"]
    validate(arguments, spec)


@pytest.mark.parametrize("tool_name", ["bridge.image", "bridge.edit"])
def test_mcp_worker_argv_forwards_explicit_image_controls_and_workspace_input(tmp_path, tool_name):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "reference.png"
    source.write_bytes(b"offline-test-image")
    gateway = Gateway(tmp_path / "jobs", "main", workspace)
    arguments = {
        "prompt": "make an icon",
        "model": "gpt-6-thinking",
        "thinking_effort": "extended",
        "level": "high",
    }
    if tool_name == "bridge.edit":
        arguments["input_images"] = ["reference.png"]

    argv = gateway.worker_argv(tool_name, arguments, tmp_path / "job")

    assert argv[argv.index("--model") + 1] == "gpt-6-thinking"
    assert argv[argv.index("--thinking-effort") + 1] == "extended"
    assert argv[argv.index("--level") + 1] == "high"
    if tool_name == "bridge.edit":
        assert argv[argv.index("--input-image") + 1] == str(source.resolve())


def test_opencode_image_tools_declare_effort_fields_and_forward_flags_statically():
    source_path = Path(__file__).resolve().parents[1] / "chatgpt_api/assets/opencode/gpt_bridge.ts"
    source = source_path.read_text()
    for name, next_name in (("image", "image_edit"), ("image_edit", "report")):
        start = source.index(f"export const {name} = tool({{")
        end = source.index(f"export const {next_name} = tool({{", start)
        tool_source = source[start:end]
        for field in ("model", "thinkingEffort", "level"):
            assert re.search(rf"\b{field}\s*:", tool_source), f"{name} schema lacks {field}"
        assert 'command.push("--model"' in tool_source
        assert 'command.push("--thinking-effort"' in tool_source
        assert 'command.push("--level"' in tool_source
