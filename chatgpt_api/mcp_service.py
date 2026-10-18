"""Operator-only macOS LaunchAgent installation; never an MCP tool."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

LABEL = "org.grunte.gpt-bridge-mcp"


def service_plist(python: Path, account: str, host: str, data_dir: Path) -> dict:
    if not python.is_absolute() or not data_dir.is_absolute():
        raise ValueError("Python and data directory must be absolute paths")
    if not account or not host.endswith(".ts.net") or any(c in host for c in "/:* "):
        raise ValueError("An account alias and exact Tailscale hostname are required")
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "chatgpt_api.mcp_gateway", "--transport", "http",
                             "--account", account, "--auth", "tailscale", "--allowed-host", host,
                             "--data-dir", str(data_dir)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "WorkingDirectory": str(data_dir),
        "StandardOutPath": str(data_dir / "service.stdout.log"),
        "StandardErrorPath": str(data_dir / "service.stderr.log"),
        "EnvironmentVariables": {"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the private MCP macOS user service")
    parser.add_argument("action", choices=["install", "status", "restart", "stop"])
    parser.add_argument("--account")
    parser.add_argument("--allowed-host")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".local/share/gpt-bridge/mcp")
    parser.add_argument("--replace", action="store_true", help="Explicitly replace an existing service configuration")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This service manager is macOS-only; use your OS service manager elsewhere")
    domain = f"gui/{os.getuid()}"
    target = domain + "/" + LABEL
    path = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    if args.action == "install":
        if not args.account or not args.allowed_host:
            parser.error("install requires --account and --allowed-host")
        root = args.data_dir.expanduser().resolve()
        try:
            config = service_plist(Path(sys.executable).absolute(), args.account, args.allowed_host, root)
        except ValueError as exc:
            parser.error(str(exc))
        if path.is_symlink():
            parser.error("Refusing a symlinked LaunchAgent")
        if path.exists() and not args.replace:
            parser.error("Service configuration exists; inspect it or pass --replace")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        for name in ("service.stdout.log", "service.stderr.log"):
            log = root / name
            if log.is_symlink():
                parser.error("Refusing symlinked service logs")
            log.touch(mode=0o600, exist_ok=True)
            log.chmod(0o600)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(config))
        path.chmod(0o600)
        if args.replace:
            subprocess.run(["/bin/launchctl", "bootout", target], capture_output=True)
        subprocess.run(["/bin/launchctl", "bootstrap", domain, str(path)], check=True)
        print(f"Installed {LABEL}; account={args.account}; endpoint=https://{args.allowed_host}/mcp")
    elif args.action == "status":
        subprocess.run(["/bin/launchctl", "print", target], check=True)
    elif args.action == "restart":
        subprocess.run(["/bin/launchctl", "kickstart", "-k", target], check=True)
    else:
        subprocess.run(["/bin/launchctl", "bootout", target], check=True)
        print("Stopped; saved LaunchAgent remains and will start at next login")


if __name__ == "__main__":
    main()
