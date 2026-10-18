"""Static/offline checks for image effort controls in consumer adapters."""

import re
from pathlib import Path


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
