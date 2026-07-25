"""Short-lived executable compatibility for web-chat-bridge-cli users."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from chatgpt_api.cli import main as chatgpt_api_main


_COMMANDS = {
    "status": ["worker", "status"],
    "doctor": ["worker", "doctor"],
    "chat": ["worker", "chat"],
    "image": ["worker", "image"],
    "report": ["worker", "report"],
    "thread": ["worker", "thread"],
    "stack": ["worker", "stack"],
}


def translate_legacy_argv(argv: Sequence[str]) -> list[str]:
    if not argv:
        return ["worker", "--help"]
    command, *rest = argv
    if command == "raw":
        if len(rest) < 2:
            return ["worker", "request", *rest]
        method, path, *flags = rest
        if path.startswith("/v1/"):
            path = path[3:]
        translated = ["worker", "request", path, "--method", method.upper()]
        for value in flags:
            translated.append("--body-json" if value == "--body" else value)
        return translated
    translated = _COMMANDS.get(command)
    if translated is None:
        return list(argv)
    mapped = [*translated]
    for value in rest:
        if command == "image" and value == "--out":
            mapped.append("--output-path")
        elif command == "chat" and value == "--no-default-system":
            mapped.extend(["--system", ""])
        else:
            mapped.append(value)
    return mapped


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    print("web-chat-bridge compatibility mode: use `gpt-bridge worker ...` for new automation.", file=sys.stderr)
    return chatgpt_api_main(translate_legacy_argv(arguments))
