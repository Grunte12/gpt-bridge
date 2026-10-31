"""Chrome-only local bootstrap. Never reads ChatGPT credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import struct
import stat
import sys

HOST = "org.gpt_bridge.pairing"


def install(extension_id: str, root: Path, *, home: Path | None = None) -> Path:
    if not re.fullmatch(r"[a-p]{32}", extension_id):
        raise ValueError("expected the GPT Bridge extension ID from chrome://extensions")
    root = root.expanduser()
    if root.is_symlink():
        raise ValueError("data directory must not be a symlink")
    root = root.resolve()
    home = home or Path.home()
    directory = root / "native-pairing"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise ValueError("native host directory must not be a symlink")
    origin = "chrome-extension://" + extension_id + "/"
    config = directory / "config.json"
    launcher = directory / ("host.cmd" if sys.platform == "win32" else "host")
    for path in (config, launcher):
        if path.is_symlink():
            raise ValueError("native host files must not be symlinks")
    config.write_text(json.dumps({"origin": origin, "data_dir": str(root)}))
    config.chmod(0o600)
    module = Path(__file__).resolve()
    if sys.platform == "win32":
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{module}" "{config}" %*\r\n')
        location = directory
    else:
        launcher.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(str(value)) for value in
                            (sys.executable, module, config)) + ' "$@"\n')
        launcher.chmod(0o700)
        location = (home / "Library/Application Support/Google/Chrome/NativeMessagingHosts" if sys.platform == "darwin"
                    else home / ".config/google-chrome/NativeMessagingHosts")
    location.mkdir(parents=True, exist_ok=True)
    manifest = location / (HOST + ".json")
    if manifest.is_symlink():
        raise ValueError("native manifest must not be a symlink")
    manifest.write_text(json.dumps({"name": HOST, "description": "GPT Bridge local Extension pairing",
                                   "path": str(launcher), "type": "stdio", "allowed_origins": [origin]}, indent=2))
    if sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\Google\\Chrome\\NativeMessagingHosts\\" + HOST) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))
    return manifest


def respond(config: dict, origin: str, request: dict) -> dict:
    if not isinstance(config, dict) or not isinstance(request, dict):
        raise ValueError("invalid native pairing message")
    if origin != config["origin"] or request != {"action": "pair"}:
        raise ValueError("native pairing request rejected")
    token_path = Path(config["data_dir"]) / "extension-token"
    info = token_path.stat()
    if token_path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 256:
        raise ValueError("local pairing file must be private")
    token = token_path.read_text().strip()
    if len(token) < 32:
        raise ValueError("invalid local pairing file")
    return {"token": token}


def main() -> int:
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    try:
        config = json.loads(Path(sys.argv[1]).read_text())
        header = sys.stdin.buffer.read(4)
        if len(header) != 4:
            return 1
        length = struct.unpack("=I", header)[0]
        if not 1 <= length <= 1024:
            return 1
        data = sys.stdin.buffer.read(length)
        if len(data) != length:
            return 1
        result = respond(config, sys.argv[2], json.loads(data))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        result = {"error": "Start the GPT Bridge MCP worker and check native host installation."}
    payload = json.dumps(result).encode()
    sys.stdout.buffer.write(struct.pack("=I", len(payload)) + payload)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
