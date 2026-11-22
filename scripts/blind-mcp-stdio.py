#!/usr/bin/env python3
"""Expose the isolated test fixture as genuine SDK MCP stdio, never live bridge."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import anyio


async def run(args):
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, CallToolResult
    command = [sys.executable, str(Path(__file__).with_name("blind-consumer-fixture.py")),
               "--scenario", args.scenario, "--log", str(args.log)]
    if args.known_job_id:
        command += ["--known-job-id", args.known_job_id]
    child = await asyncio.create_subprocess_exec(*command,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    lock = asyncio.Lock()
    async def exchange(payload):
        async with lock:
            child.stdin.write((json.dumps(payload)+"\n").encode())
            await child.stdin.drain()
            response = json.loads(await child.stdout.readline())
            if "error" in response:
                raise ValueError(response["error"])
            return response["result"]
    try:
        ready = json.loads(await child.stdout.readline())
        if args.manifest:
            args.manifest.write_text(json.dumps(ready)+"\n")
        server = Server("gpt-bridge", instructions=ready["instructions"])
        surface = await exchange({"op": "list"})
        schemas = [Tool.model_validate(await exchange({"op":"describe", "name":t["name"]})) for t in surface]
        @server.list_tools()
        async def tools():
            return schemas
        @server.call_tool()
        async def call(name, arguments):
            return CallToolResult.model_validate(await exchange({"op":"call", "name":name, "arguments":arguments}))
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        with anyio.CancelScope(shield=True):
            if child.returncode is None:
                child.stdin.write(b'{"op":"quit"}\n')
                await child.stdin.drain()
                await child.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=["A", "B"])
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--known-job-id")
    asyncio.run(run(parser.parse_args()))
