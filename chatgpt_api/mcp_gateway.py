"""Private MCP adapter: lazy discovery, bounded results, CLI jobs, scoped files.

The worker runs as a child process with argv (never a shell), preserving its
existing account selection, image postprocessing, and cleanup behavior.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hmac
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1, "maxLength": 64000}
PATH = {"type": "string", "minLength": 1, "maxLength": 1024}
LEVEL = {"type": "string", "enum": ["instant", "medium", "high"]}


CATALOG = {
    "bridge.chat": ("Ask ChatGPT; optional local task thread.", schema({"message": TEXT, "thread": PATH, "level": LEVEL}, ["message"])),
    "bridge.report": ("Generate an HTML report saved as an artifact.", schema({"prompt": TEXT}, ["prompt"])),
    "bridge.image": ("Generate a PNG; optional alpha and one-shot cleanup.", schema({"prompt": TEXT, "transparent": {"type": "boolean"}, "cleanup_session": {"type": "boolean"}}, ["prompt"])),
    "bridge.edit": ("Edit/composite up to ten workspace images.", schema({"prompt": TEXT, "input_images": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 10}, "transparent": {"type": "boolean"}, "cleanup_session": {"type": "boolean"}}, ["prompt", "input_images"])),
    "bridge.research": ("Long-running sourced research saved locally.", schema({"prompt": TEXT}, ["prompt"])),
    "bridge.web_list": ("Find existing ChatGPT conversations by title.", schema({"query": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 20}})),
    "bridge.web_read": ("Export an existing conversation to an artifact.", schema({"conversation": TEXT}, ["conversation"])),
    "bridge.web_continue": ("Continue a specific ChatGPT conversation without replaying it.", schema({"conversation": TEXT, "message": TEXT}, ["conversation", "message"])),
    "workspace.read": ("Read a bounded text slice inside the configured workspace.", schema({"path": PATH, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 8000}}, ["path"])),
    "workspace.replace": ("Replace one exact text occurrence; fails if ambiguous or changed.", schema({"path": PATH, "old": TEXT, "new": {"type": "string", "maxLength": 64000}}, ["path", "old", "new"])),
    "workspace.test": ("Run an operator-configured test command by name.", schema({"name": PATH}, ["name"])),
    "artifact.read": ("Read bounded text or explicit base64 chunks of a job artifact.", schema({"job_id": PATH, "name": PATH, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 8000}, "encoding": {"type": "string", "enum": ["text", "base64"]}}, ["job_id", "name"])),
}


class Gateway:
    def __init__(self, root: Path, account: str, workspace: Path | None = None,
                 test_commands: dict[str, list[str]] | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.account = account
        self.workspace = workspace.resolve() if workspace else None
        self.test_commands = test_commands or {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.semaphore = asyncio.Semaphore(1)

    def save_job(self, job_id: str) -> None:
        directory = self.root / job_id
        temporary = directory / ".job-state.tmp"
        temporary.write_text(json.dumps(self.jobs[job_id]))
        temporary.chmod(0o600)
        temporary.replace(directory / ".job-state.json")

    def restore_job(self, job_id: str) -> None:
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("unknown job")
        path = self.root / job_id / ".job-state.json"
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError("unknown job")
        if path.stat().st_size > 16000:
            raise ValueError("invalid job state")
        record = json.loads(path.read_text())
        if not isinstance(record, dict) or record.get("job_id") != job_id:
            raise ValueError("invalid job state")
        self.jobs[job_id] = record
        if record.get("state") in {"running", "queued"}:
            record.update(state="interrupted", error_code="server_restarted",
                          next_action="Inspect saved artifacts and ChatGPT history before retrying; upstream work may have completed")
            self.save_job(job_id)

    def search(self, query: str = "", detail: str = "brief", limit: int = 5) -> dict:
        words = query.lower().split()
        candidates = [(sum(w in (name + " " + desc).lower() for w in words), name, desc, spec)
                      for name, (desc, spec) in CATALOG.items()
                      if not name.startswith("workspace.") or self.workspace]
        candidates.sort(key=lambda row: (-row[0], row[1]))
        hits = [{"name": name, "description": desc, **({"input_schema": spec} if detail == "schema" else {})}
                for score, name, desc, spec in candidates if not words or score]
        return {"tools": hits[:max(1, min(limit, 10))], "more": len(hits) > limit}

    def workspace_path(self, value: str) -> Path:
        if not self.workspace:
            raise ValueError("workspace access is disabled")
        path = (self.workspace / value).resolve()
        if not path.is_relative_to(self.workspace):
            raise ValueError("path is outside configured workspace")
        if any(part.startswith(".") or part in {"secrets", "accounts", "node_modules"}
               for part in path.relative_to(self.workspace).parts):
            raise ValueError("private or generated path is excluded")
        return path

    async def call(self, name: str, arguments: dict) -> dict:
        from jsonschema import validate
        if name not in CATALOG:
            raise ValueError("unknown tool; use search_tools")
        validate(arguments, CATALOG[name][1])
        if name == "artifact.read":
            return self.read_artifact(**arguments)
        if name == "workspace.read":
            path = self.workspace_path(arguments["path"])
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("file too large; use a smaller artifact")
            text = path.read_text()
            offset, limit = arguments.get("offset", 0), arguments.get("limit", 4000)
            return {"text": text[offset:offset + limit], "next_offset": min(len(text), offset + limit), "total": len(text)}
        if name == "workspace.replace":
            path = self.workspace_path(arguments["path"])
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("file too large")
            text = path.read_text()
            if text.count(arguments["old"]) != 1:
                raise ValueError("old text must match exactly once")
            path.write_text(text.replace(arguments["old"], arguments["new"], 1))
            return {"updated": arguments["path"]}
        if sum(not task.done() for task in self.tasks.values()) >= 100:
            raise ValueError("active job capacity reached; wait for pending work")
        job_id = uuid.uuid4().hex
        directory = self.root / job_id
        directory.mkdir()
        if name == "workspace.test":
            if not self.workspace:
                raise ValueError("workspace access is disabled")
            argv = self.test_commands.get(arguments["name"])
            if not argv:
                raise ValueError("unknown configured test command")
            cwd = self.workspace
        else:
            argv = self.worker_argv(name, arguments, directory)
            cwd = directory
        self.jobs[job_id] = {"job_id": job_id, "state": "queued", "tool": name}
        self.save_job(job_id)
        self.tasks[job_id] = asyncio.create_task(self.run_job(job_id, argv, cwd, directory))
        return dict(self.jobs[job_id])

    def worker_argv(self, name: str, args: dict, directory: Path) -> list[str]:
        argv = [sys.executable, "-m", "chatgpt_api", "worker", "--account", self.account]
        action = name.removeprefix("bridge.")
        if action.startswith("web_"):
            argv += ["web", {"web_list": "list", "web_read": "show", "web_continue": "send"}[action]]
        else:
            argv += [action]
        for key, flag in {"message": "--message", "prompt": "--prompt", "thread": "--thread", "level": "--level", "query": "--query", "limit": "--limit", "conversation": "--conversation"}.items():
            if key in args:
                argv += [flag, str(args[key])]
        if action in {"image", "edit"}:
            argv += ["--output-path", str(directory / "image.png"), "--brief"]
            for key, flag in {"transparent": "--transparent", "cleanup_session": "--cleanup-session"}.items():
                if args.get(key):
                    argv.append(flag)
            for source in args.get("input_images", []):
                argv += ["--input-image", str(self.workspace_path(source))]
        else:
            argv.append("--json")
            if action == "report":
                argv += ["--out", str(directory / "report.html")]
            elif action == "research":
                argv += ["--output-path", str(directory / "research.md")]
            elif action in {"web_read", "web_continue"}:
                argv += ["--output", str(directory / "conversation.md")]
        return argv

    async def run_job(self, job_id: str, argv: list[str], cwd: Path, directory: Path):
        try:
            async with self.semaphore:
                self.jobs[job_id]["state"] = "running"
                self.save_job(job_id)
                # Logs stay local, never dumped into model context automatically.
                with (directory / "result.txt").open("wb") as out, (directory / "stderr.log").open("wb") as err:
                    process = await asyncio.create_subprocess_exec(*argv, cwd=cwd, stdout=out, stderr=err)
                    self.processes[job_id] = process
                    try:
                        code = await asyncio.wait_for(process.wait(), timeout=5400)
                    finally:
                        if process.returncode is None:
                            process.terminate()
                            try:
                                await asyncio.wait_for(process.wait(), timeout=3)
                            except asyncio.TimeoutError:
                                process.kill()
                                await process.wait()
                self.jobs[job_id].update(state="completed" if code == 0 else "failed", exit_code=code)
                if code:
                    # Classify only known markers; never return stderr or token values.
                    with (directory / "stderr.log").open("rb") as source:
                        diagnostic = source.read(16000).decode("utf-8", errors="replace").lower()
                    if any(marker in diagnostic for marker in ("token_invalidated", "401", "session expired", "token expired")):
                        self.jobs[job_id].update(error_code="account_auth_rejected", next_action=f"Refresh local capture with gpt-bridge setup --account {self.account}")
                    elif "not configured" in diagnostic or "missing account" in diagnostic:
                        self.jobs[job_id].update(error_code="account_not_configured", next_action="Configure the selected local account")
                    elif "429" in diagnostic or "rate limit" in diagnostic:
                        self.jobs[job_id].update(error_code="upstream_rate_limit", next_action="Wait before retrying")
                    else:
                        self.jobs[job_id].update(error_code="worker_failed", next_action="Inspect local stderr.log")
        except asyncio.CancelledError:
            self.jobs[job_id]["state"] = "cancelled"
            raise
        except Exception:
            self.jobs[job_id].update(state="failed", error="execution failed; inspect local logs")
        finally:
            self.processes.pop(job_id, None)
            self.save_job(job_id)
            # Completed metadata remains on disk, not in the long-lived server cache.
            self.tasks.pop(job_id, None)
            self.jobs.pop(job_id, None)

    async def status(self, job_id: str, wait_seconds: int = 0, cancel: bool = False) -> dict:
        if job_id not in self.jobs:
            self.restore_job(job_id)
        task = self.tasks.get(job_id)
        if cancel and task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if job_id not in self.jobs:
                self.restore_job(job_id)
            self.jobs[job_id]["state"] = "cancelled"
            self.save_job(job_id)
            self.tasks.pop(job_id, None)
        elif task is not None and not task.done() and wait_seconds:
            await asyncio.wait([task], timeout=min(max(wait_seconds, 0), 30))
        if job_id not in self.jobs:
            self.restore_job(job_id)
        result = dict(self.jobs[job_id])
        directory = self.root / job_id
        result["artifacts"] = [{"name": p.name, "bytes": p.stat().st_size,
                                "download_path": f"/artifacts/{job_id}/{p.name}"}
                               for p in directory.iterdir() if p.is_file() and not p.is_symlink() and not p.name.startswith(".") and p.name != "stderr.log"]
        if task is None or task.done():
            self.jobs.pop(job_id, None)
        if cancel:
            result["note"] = "local worker cancelled; upstream work may still complete"
        return result

    def read_artifact(self, job_id: str, name: str, offset: int = 0, limit: int = 4000, encoding: str = "text") -> dict:
        if job_id not in self.jobs:
            self.restore_job(job_id)
            self.jobs.pop(job_id, None)
        if Path(name).name != name or name == "stderr.log" or name.startswith("."):
            raise ValueError("unknown artifact")
        path = self.root / job_id / name
        if path.is_symlink():
            raise ValueError("unknown artifact")
        with path.open("rb") as source:
            source.seek(offset)
            chunk = source.read(limit)
        return {"data": base64.b64encode(chunk).decode() if encoding == "base64" else chunk.decode("utf-8", errors="replace"),
                "encoding": encoding, "next_offset": offset + len(chunk), "bytes": path.stat().st_size}


def create_server(gateway: Gateway, hosts: list[str]):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    server = FastMCP("GPT Bridge", stateless_http=True, json_response=True,
                     instructions="Search tools, request the selected schema, then call_tool. Jobs return IDs; read only needed artifacts.",
                     transport_security=TransportSecuritySettings(allowed_hosts=["127.0.0.1", "localhost", "127.0.0.1:*", "localhost:*", *hosts], allowed_origins=["https://" + h for h in hosts]))

    @server.tool()
    def search_tools(query: str = "", detail: str = "brief", limit: int = 5) -> dict:
        """Find capabilities; detail=schema loads only matching argument schemas."""
        return gateway.search(query, detail, limit)

    @server.tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict:
        """Invoke a discovered capability. Long work returns a job_id."""
        return await gateway.call(name, arguments)

    @server.tool()
    async def job_status(job_id: str, wait_seconds: int = 0, cancel: bool = False) -> dict:
        """Get compact state/artifacts; wait at most 30s or cancel local work."""
        return await gateway.status(job_id, wait_seconds, cancel)

    return server


class BearerAuth:
    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            value = headers.get(b"authorization", b"").decode("latin-1")
            if not hmac.compare_digest(value, "Bearer " + self.token):
                from starlette.responses import JSONResponse
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class TailscaleAuth:
    """Trust Serve identity headers only from the local reverse proxy.

    Local processes are trusted; never bind this backend to a network interface.
    Tagged nodes without user identity must use bearer mode instead.
    """

    def __init__(self, app, allowed_hosts: list[str]):
        self.app, self.allowed_hosts = app, set(allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            peer = (scope.get("client") or ("", 0))[0]
            host = headers.get(b"host", b"").decode("latin-1")
            if (peer not in {"127.0.0.1", "::1"}
                    or host not in self.allowed_hosts | {h + ":443" for h in self.allowed_hosts}
                    or not headers.get(b"tailscale-user-login", b"").strip()
                    or b"tailscale-funnel-request" in headers):
                from starlette.responses import JSONResponse
                await JSONResponse({"error": "tailscale_serve_identity_required"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def http_app(gateway: Gateway, server, token: str | None, allowed_hosts: list[str] | None = None):
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Route

    async def download(request):
        job_id, name = request.path_params["job_id"], request.path_params["name"]
        if job_id not in gateway.jobs:
            try:
                gateway.restore_job(job_id)
                gateway.jobs.pop(job_id, None)
            except (ValueError, OSError):
                return JSONResponse({"error": "unknown artifact"}, status_code=404)
        if Path(name).name != name or name == "stderr.log" or name.startswith("."):
            return JSONResponse({"error": "unknown artifact"}, status_code=404)
        path = gateway.root / job_id / name
        if not path.is_file() or path.is_symlink():
            return JSONResponse({"error": "unknown artifact"}, status_code=404)
        return FileResponse(path, filename=name, headers={"Cache-Control": "no-store"})

    app = server.streamable_http_app()
    async def health(request):
        return JSONResponse({"status": "ready", "service": "gpt-bridge-mcp", "active_jobs": sum(not t.done() for t in gateway.tasks.values()), "provider_verified": False}, headers={"Cache-Control": "no-store"})
    app.routes.append(Route("/healthz", health))
    app.routes.append(Route("/artifacts/{job_id}/{name}", download))
    if token is None:
        if not allowed_hosts:
            raise ValueError("Tailscale authentication requires an exact Serve hostname")
        return TailscaleAuth(app, allowed_hosts)
    return BearerAuth(app, token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Private GPT Bridge MCP (stdio or localhost HTTP)")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--account", required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--test-commands", type=Path, help="JSON object of names to fixed argv lists")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".local/share/gpt-bridge/mcp")
    parser.add_argument("--allowed-host", action="append", default=[], help="Exact tailnet HTTPS hostname")
    parser.add_argument("--auth", choices=["bearer", "tailscale"], default="bearer", help="HTTP authentication; tailscale trusts local Serve identity headers")
    parser.add_argument("--token-file", type=Path, help="Private bearer-token file; generated if missing (HTTP only)")
    args = parser.parse_args()
    if args.auth == "tailscale" and (args.transport != "http" or not args.allowed_host):
        parser.error("--auth tailscale requires --transport http and --allowed-host")
    tests = json.loads(args.test_commands.read_text()) if args.test_commands else {}
    if not isinstance(tests, dict) or any(not isinstance(v, list) or not v or any(not isinstance(x, str) for x in v) for v in tests.values()):
        parser.error("test commands must be nonempty argv lists")
    gateway = Gateway(args.data_dir, args.account, args.workspace, tests)
    # One server owns a data directory; otherwise recovery could mistake live
    # jobs in another process for interrupted work.
    lock = None
    if os.name == "posix":
        import fcntl
        lock = (gateway.root / ".server.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("another MCP server already owns this data directory")
    server = create_server(gateway, args.allowed_host)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        if args.auth == "tailscale":
            import uvicorn
            uvicorn.run(http_app(gateway, server, None, args.allowed_host), host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)
            return
        token = os.environ.get("GPT_BRIDGE_MCP_TOKEN", "")
        if not token:
            token_path = args.token_file or gateway.root / "access-token"
            if not token_path.exists():
                token_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    output.write(secrets.token_urlsafe(32))
            if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
                parser.error("token file must be private (chmod 600) and not a symlink")
            token = token_path.read_text().strip()
            print(f"Bearer token stored locally: {token_path}", file=sys.stderr)
        if len(token) < 32 or not token.isascii():
            parser.error("bearer token must contain at least 32 ASCII characters")
        import uvicorn
        uvicorn.run(http_app(gateway, server, token), host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
