#!/usr/bin/env python3
"""Opt-in isolated MCP readiness gate. Never connects to the production owner.

From the repository root:
    .venv/bin/python scripts/mcp-readiness-smoke.py --output /tmp/mcp-smoke.json

Requires local loopback permission. Uses two real stdio MCP sessions, a fresh
temporary queue, an ephemeral loopback owner, and synthetic browser messages.
No provider/browser is contacted. Exit code is nonzero when any check fails.
"""
import argparse
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
CLIENT = "123e4567-e89b-12d3-a456-426614174000"
TOKEN = "synthetic-local-token-with-enough-length"


async def run():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from PIL import Image
    from chatgpt_api.extension_bridge import ExtensionQueue, make_handler

    receipt = {"transport": "two independent stdio MCP sessions; real isolated HTTP owner",
               "checks": [], "observations": []}

    def check(name, value):
        receipt["checks"].append({"name": name, "pass": bool(value)})

    with tempfile.TemporaryDirectory(prefix="bridge-blackbox-") as temp:
        queue = ExtensionQueue(Path(temp), "test")
        http = ThreadingHTTPServer(("127.0.0.1", 0), lambda *args: None)
        port = http.server_address[1]
        http.RequestHandlerClass = make_handler(queue, TOKEN, port)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))

        def chrome(route, **data):
            request = Request(f"http://127.0.0.1:{port}/{route}",
                              data=json.dumps({"client_id": CLIENT, **data}).encode(),
                              headers={"Authorization": "Bearer " + TOKEN,
                                       "Content-Type": "application/json"})
            with opener.open(request, timeout=10) as reply:
                return json.load(reply)

        def beat(ready, error=""):
            return chrome("heartbeat", account="test", tab_ready=ready, input_protocol=3,
                          content_receiver="available", tab_error=error)

        try:
            chrome("pair", account="test", input_protocol=3, visible_model="Create image")
            beat(True)
            # Do not inherit credentials, provider configuration, or proxy settings.
            child_env = {"PYTHONPATH": str(REPO), "PYTHONUNBUFFERED": "1"}
            if os.name == "nt" and "SYSTEMROOT" in os.environ:
                child_env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
            params = StdioServerParameters(command=sys.executable,
                                          args=[str(Path(__file__).resolve()), "--stdio-port", str(port)],
                                          env=child_env)
            async with stdio_client(params) as (r1, w1), stdio_client(params) as (r2, w2):
                async with ClientSession(r1, w1) as a, ClientSession(r2, w2) as b:
                    await asyncio.gather(a.initialize(), b.initialize())

                    async def call(session, tool, **args):
                        result = await session.call_tool(tool, args)
                        texts = [part.text for part in result.content if hasattr(part, "text")]
                        return {"mcp_error": texts} if result.isError else json.loads(texts[0])

                    cases = [
                        ("Remove existing attachments before using the image worker",
                         "existing_attachments", "preserve_paired_attachments"),
                        ("ChatGPT composer unavailable. Nothing was submitted.",
                         "composer_unavailable", "inspect_paired_composer"),
                    ]
                    for index, (error, reason, action) in enumerate(cases):
                        beat(False, error)
                        first = await call(a, "enqueue", request_id=f"a-{index}", prompt=f"Synthetic A {index}")
                        second = await call(b, "enqueue", request_id=f"b-{index}", prompt=f"Synthetic B {index}")
                        duplicate = await call(b, "enqueue", request_id=f"a-{index}", prompt=f"Synthetic A {index}")
                        conflict = await call(b, "enqueue", request_id=f"a-{index}", prompt="Different intent")
                        check(f"{index}: two accepted intents", first.get("job_id") and second.get("job_id"))
                        check(f"{index}: duplicate stable", first.get("job_id") and first.get("job_id") == duplicate.get("job_id"))
                        check(f"{index}: changed duplicate rejected", conflict.get("mcp_error"))
                        blocked = chrome("next")
                        check(f"{index}: blocked claim empty", blocked == {})
                        global_status = await call(b, "status")
                        check(f"{index}: global guidance", global_status.get("next_action") == action)
                        sample = {"error": error, "enqueue_a": first, "enqueue_b": second,
                                  "blocked_claim": blocked, "global_status": global_status}
                        receipt["observations"].append(sample)
                        if not first.get("job_id") or not second.get("job_id"):
                            continue
                        for tool in ["job", "status", "wait"]:
                            value = await call(a, tool, job_id=first["job_id"],
                                               **({"timeout_seconds": 1} if tool == "wait" else {}))
                            sample[tool] = value
                            check(f"{index}: {tool} exact guidance", value.get("wait_reason") == reason
                                  and value.get("next_action") == action)
                        beat(True)
                        resumed = await call(a, "enqueue", request_id=f"a-{index}", prompt=f"Synthetic A {index}")
                        check(f"{index}: stable ID after readiness", resumed.get("job_id") == first["job_id"])
                        delivered = []
                        for expected in [first["job_id"], second["job_id"]]:
                            claimed = chrome("next")
                            delivered.append(claimed.get("job_id"))
                            check(f"{index}: no double delivery {expected}", chrome("next") == {})
                            if claimed.get("job_id"):
                                png = io.BytesIO()
                                Image.new("RGB", (512, 512), (20, 60, 90)).save(png, format="PNG")
                                chrome("result", job_id=claimed["job_id"],
                                       image_base64=base64.b64encode(png.getvalue()).decode())
                        check(f"{index}: resumed FIFO", delivered == [first["job_id"], second["job_id"]])
                        check(f"{index}: no resubmit", chrome("next") == {})
                        sample.update(delivered=delivered, total_dispatches=sum(bool(j) for j in delivered) + bool(blocked))
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)
    receipt["pass"] = bool(receipt["checks"]) and all(check["pass"] for check in receipt["checks"])
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON receipt path")
    parser.add_argument("--stdio-port", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.stdio_port is not None:
        if not 1 <= args.stdio_port <= 65535:
            parser.error("invalid isolated loopback port")
        import chatgpt_api.extension_bridge as bridge
        bridge.PORT = args.stdio_port
        bridge.create_mcp(bridge.ExtensionClient(TOKEN)).run(transport="stdio")
        return 0
    receipt = asyncio.run(run())
    if args.output:
        args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
