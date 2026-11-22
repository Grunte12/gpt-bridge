#!/usr/bin/env python3
"""Test-only JSONL client for the real isolated GPT Bridge MCP.

Run .venv/bin/python scripts/blind-consumer-fixture.py --scenario A --log /tmp/a.jsonl
Input lines: {"op":"list"}, {"op":"describe","name":"enqueue"},
{"op":"call","name":"status","arguments":{}}, {"op":"quit"}.
No live browser, credentials, or generation. Private audit goes only to --log.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch
from http.server import ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
CLIENT = "123e4567-e89b-12d3-a456-426614174000"
TOKEN = "synthetic-local-token-with-enough-length"


async def run(args):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from chatgpt_api.extension_bridge import ExtensionQueue, make_handler
    start = time.monotonic()
    with args.log.open("x") as audit, tempfile.TemporaryDirectory(prefix="blind-consumer-") as temp:
        def log(kind, **data):
            audit.write(json.dumps({"kind": kind, "elapsed_seconds": time.monotonic()-start, **data})+"\n")
            audit.flush()

        queue = ExtensionQueue(Path(temp), "test")
        queue.pair(CLIENT, account="test", visible_model="Create image", input_protocol=3, tab_id=71)
        queue.heartbeat(CLIENT, account="test", tab_ready=True, input_protocol=3, tab_id=71,
                        content_receiver="available")
        known_id = None
        if args.scenario == "B":
            if args.known_job_id:
                with patch("chatgpt_api.extension_bridge.uuid.uuid4", return_value=uuid.UUID(hex=args.known_job_id)):
                    original = queue.enqueue("prior-order-uncertain", "A cobalt blue teapot on a white table")
            else:
                original = queue.enqueue("prior-order-uncertain", "A cobalt blue teapot on a white table")
            known_id = original["job_id"]
            claimed = queue.claim(CLIENT)
            queue.phase(CLIENT, known_id, "submit_attempted", 71)
            log("seed_delivery", claimed=claimed)
            queue = ExtensionQueue(Path(temp), "test")
            queue.pair(CLIENT, account="test", visible_model="Create image", input_protocol=3, tab_id=71)
        def beat():
            queue.heartbeat(CLIENT, account="test", tab_ready=args.scenario != "A", input_protocol=3, tab_id=71,
                            content_receiver="available", tab_error=("Remove existing attachments before using the image worker" if args.scenario == "A" else ""))
        beat()
        http = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: None)
        port = http.server_address[1]
        http.RequestHandlerClass = make_handler(queue, TOKEN, port)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        env = {"PYTHONPATH": str(REPO), "PYTHONUNBUFFERED": "1"}
        if os.name == "nt" and "SYSTEMROOT" in os.environ:
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve()), "--stdio-port", str(port)], env=env)
        try:
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    print(json.dumps({"ready": True, "known_job_id": known_id, "instructions": initialized.instructions}), flush=True)
                    log("start", scenario=args.scenario, known_job_id=known_id)
                    while True:
                        line = await asyncio.to_thread(sys.stdin.readline)
                        if not line:
                            break
                        try:
                            request = json.loads(line)
                            op = request.get("op")
                            if op == "quit":
                                break
                            if op == "list":
                                result = [{"name": t.name, "description": t.description} for t in tools.tools]
                            elif op == "describe":
                                result = next(t.model_dump(mode="json") for t in tools.tools if t.name == request["name"])
                            elif op == "call":
                                beat()
                                before = {k: dict(v) for k, v in queue.jobs.items()}
                                called = time.monotonic()
                                arguments = request.get("arguments", {})
                                if request["name"] in {"batch_start", "preflight", "edit"} or arguments.get("images"):
                                    log("unsafe_attempt", name=request["name"], arguments=arguments,
                                        reason="local files and batch paths are outside this text-only fixture")
                                    result = {"isError": True, "content": [{"type":"text", "text":"This isolated text-only transport forbids local image and batch path access."}]}
                                    print(json.dumps({"result": result}), flush=True)
                                    continue
                                response = await session.call_tool(request["name"], arguments)
                                result = response.model_dump(mode="json")
                                log("call", name=request["name"], arguments=request.get("arguments", {}), result=result,
                                    duration_seconds=time.monotonic()-called, before=before, after=queue.jobs,
                                    halted_job=queue.halted_job)
                            else:
                                raise ValueError("op must be list, describe, call, or quit")
                            if op != "call":
                                log("discovery", request=request)
                            print(json.dumps({"result": result}), flush=True)
                        except Exception as error:
                            log("error", error=str(error))
                            print(json.dumps({"error": str(error)}), flush=True)
        finally:
            log("final_claim", claimed=queue.claim(CLIENT))
            log("final", jobs=queue.jobs, halted_job=queue.halted_job)
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["A", "B"])
    parser.add_argument("--log", type=Path)
    parser.add_argument("--stdio-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--known-job-id", help="Optional test-only B seed ID (32 hexadecimal characters)")
    args = parser.parse_args()
    if args.stdio_port is not None:
        import chatgpt_api.extension_bridge as bridge
        bridge.PORT = args.stdio_port
        bridge.create_mcp(bridge.ExtensionClient(TOKEN)).run(transport="stdio")
        return
    if not args.scenario or not args.log:
        parser.error("--scenario and --log required")
    if args.known_job_id and (len(args.known_job_id) != 32 or any(c not in "0123456789abcdef" for c in args.known_job_id)):
        parser.error("--known-job-id must be 32 lowercase hexadecimal characters")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
