"""Public CLI for the Chrome Extension transport; no captured ChatGPT credentials."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from chatgpt_api import extension_bridge as bridge

    parser = argparse.ArgumentParser(prog="gpt-bridge", description="Use the ChatGPT login in your paired Chrome tab. No cookie setup or account selection.")
    commands = parser.add_subparsers(dest="command", required=True)
    mcp = commands.add_parser("mcp", help="Run Extension MCP")
    mode = mcp.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true", help="Run the shared loopback worker")
    mode.add_argument("--connect", action="store_true", help="Connect to an existing worker")
    mcp.add_argument("--auto-delete-saved-chats", action="store_true")
    native = commands.add_parser("install-native", help="Agent setup: enable automatic Chrome Extension pairing")
    native.add_argument("--extension-id", required=True, help="GPT Bridge ID shown by chrome://extensions")
    for name in ("status", "doctor", "pairing"):
        command = commands.add_parser(name, help="Show local pairing code" if name == "pairing" else "Check Extension connection")
        if name != "pairing":
            command.add_argument("--json", action="store_true")
    for command in commands.choices.values():
        command.add_argument("--data-dir", type=Path, default=bridge.default_data_dir())
    args = parser.parse_args(argv)
    root = args.data_dir.expanduser()
    if root.is_symlink():
        parser.error("data directory must not be a symlink")
    try:
        if args.command == "install-native":
            from chatgpt_api.native_pairing import install
            print("Native pairing installed: " + str(install(args.extension_id, root)))
            return 0
        if args.command == "mcp":
            options = ["--data-dir", str(root)]
            if args.serve:
                options.append("--serve")
            elif args.connect:
                options.append("--connect")
            elif (root / "extension-token").exists():
                try:
                    bridge.ExtensionClient(bridge.read_token(root)).status()
                except ValueError:
                    pass  # The owning worker lock still prevents duplicate queues.
                else:
                    if args.auto_delete_saved_chats:
                        parser.error("change cleanup policy on the existing owner, not a connected client")
                    options.append("--connect")
            if args.auto_delete_saved_chats:
                options.append("--auto-delete-saved-chats")
            bridge.main(options)
            return 0
        token = bridge.read_token(root)
        if args.command == "pairing":
            print("Local pairing code: paste only into the GPT Bridge Extension popup.")
            print(token)
        else:
            print(json.dumps(bridge.compact_status(bridge.ExtensionClient(token).status()), ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as error:
        result = {"ready": False, "error": str(error), "next_action": "Start gpt-bridge mcp and pair the Extension on a logged-in ChatGPT tab. No cookies or account aliases needed."}
        print(json.dumps(result, ensure_ascii=False), file=sys.stdout if getattr(args, "json", False) else sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
