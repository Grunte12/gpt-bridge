#!/usr/bin/env python3
"""Joined offline MCP/MV3/DOM gate. Requires Playwright Chromium; no provider calls.

Run with the same Python environment as mcp-readiness-smoke.py. Set
PLAYWRIGHT_MODULE when Playwright is installed outside Node's normal lookup.
"""
import argparse
import asyncio
import base64
import hashlib
import importlib.util
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
spec = importlib.util.spec_from_file_location("readiness_smoke", REPO / "scripts/mcp-readiness-smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


async def run():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from PIL import Image
    from chatgpt_api.extension_bridge import ExtensionQueue, make_handler

    receipt = {"checks": [], "observations": [], "seams": [
        "offline composer HTML, not ChatGPT", "fixture-owned pairing config",
        "image-job acceptance and PNG completion synthetic",
        "temp worker endpoint/host permission changed; nativeMessaging removed",
    ]}

    def check(name, value):
        receipt["checks"].append({"name": name, "pass": bool(value)})
        assert value, name

    with tempfile.TemporaryDirectory(prefix="bridge-mcp-chromium-") as temp:
        queue = ExtensionQueue(Path(temp), "test")
        http = ThreadingHTTPServer(("127.0.0.1", 0), lambda *args: None)
        port = http.server_address[1]
        assert port != 18767
        http.RequestHandlerClass = make_handler(queue, smoke.TOKEN, port)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))

        def chrome(route, **data):
            request = Request(f"http://127.0.0.1:{port}/{route}",
                              data=json.dumps({"client_id": smoke.CLIENT, **data}).encode(),
                              headers={"Authorization": "Bearer " + smoke.TOKEN,
                                       "Content-Type": "application/json"})
            with opener.open(request, timeout=10) as reply:
                return json.load(reply)

        browser = None
        try:
            chrome("pair", account="test", input_protocol=3, visible_model="Create image")
            browser = await asyncio.create_subprocess_exec(
                "node", str(REPO / "tests/mcp_chromium_driver.cjs"), str(port),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                env=os.environ.copy())

            async def read():
                line = await asyncio.wait_for(browser.stdout.readline(), timeout=60)
                if not line:
                    raise RuntimeError("Chromium driver exited before replying")
                value = json.loads(line)
                if "driver_error" in value:
                    raise RuntimeError(value["driver_error"])
                return value

            async def command(op, **data):
                browser.stdin.write((json.dumps({"op": op, **data}) + "\n").encode())
                await browser.stdin.drain()
                return await read()

            receipt["browser"] = await read()
            await command("configure", token=smoke.TOKEN, clientId=smoke.CLIENT)
            child_env = {"PYTHONPATH": str(REPO), "PYTHONUNBUFFERED": "1"}
            if os.name == "nt" and "SYSTEMROOT" in os.environ:
                child_env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
            params = StdioServerParameters(command=sys.executable,
                                          args=[str(REPO / "scripts/mcp-readiness-smoke.py"),
                                                "--stdio-port", str(port)], env=child_env)
            async with stdio_client(params) as (r1, w1), stdio_client(params) as (r2, w2):
                async with ClientSession(r1, w1) as a, ClientSession(r2, w2) as b:
                    await asyncio.gather(a.initialize(), b.initialize())

                    async def call(session, tool, **args):
                        result = await session.call_tool(tool, args)
                        assert not result.isError, str(result.content)
                        return json.loads(next(part.text for part in result.content if hasattr(part, "text")))

                    first = await call(a, "enqueue", request_id="joined-a", prompt="Offline fixture A")
                    second = await call(b, "enqueue", request_id="joined-b", prompt="Offline fixture B")
                    ids = [first["job_id"], second["job_id"]]
                    receipt["job_ids"] = ids
                    check("real content attachment blocks both queued intents", not (await command("poll"))["deliveries"])
                    for tool in ["job", "status", "wait"]:
                        value = await call(a, tool, job_id=ids[0], **({"timeout_seconds": 1} if tool == "wait" else {}))
                        check(tool + " reports actual attachment hold", value.get("wait_reason") == "existing_attachments"
                              and value.get("next_action") == "preserve_paired_attachments")
                        receipt["observations"].append({"tool": tool, "value": value})
                    missing = await command("dom", mode="missing")
                    check("missing composer sends no work", missing["deliveries"] == [])
                    value = await call(b, "job", job_id=ids[0])
                    check("same job changes hold from actual DOM", value.get("wait_reason") == "composer_unavailable")
                    clean = await command("dom", mode="clean")
                    check("clean DOM releases first original ID", clean["deliveries"] == ids[:1])
                    check("active job cannot double dispatch", (await command("poll"))["deliveries"] == ids[:1])
                    png = io.BytesIO()
                    Image.new("RGB", (512, 512), (20, 60, 90)).save(png, format="PNG")
                    raw = png.getvalue()
                    digest = hashlib.sha256(raw).hexdigest()
                    for index, job_id in enumerate(ids):
                        chat_path = f"/c/123e4567-e89b-12d3-a456-42661417400{index}"
                        for phase in ["submit_attempted", "remote_started", "result_captured"]:
                            chrome("phase", job_id=job_id, phase=phase,
                                   tab_id=receipt["browser"]["tabId"],
                                   chat_path="" if phase == "submit_attempted" else chat_path)
                        chrome("result", job_id=job_id, image_base64=base64.b64encode(raw).decode(), chat_path=chat_path)
                        saved = await call(a, "job", job_id=job_id)
                        check(f"{index}: saved output bytes and hash", saved.get("state") == "complete"
                              and saved.get("sha256") == digest
                              and Path(saved["image_path"]).read_bytes() == raw)
                        receipt["observations"].append({"job_id": job_id, "sha256": digest, "bytes": len(raw)})
                        delivered = await command("poll")
                        check(f"{index}: once-only FIFO", delivered["deliveries"] == ids[:min(index + 2, 2)])
                    check("finished queue never replays", (await command("poll"))["deliveries"] == ids)
                    reloaded = ExtensionQueue(Path(temp), "test")
                    for job_id in ids:
                        persisted = reloaded.status(job_id)
                        check("disk reload retains " + job_id, persisted.get("state") == "complete"
                              and persisted.get("sha256") == digest)
                    receipt["network"] = await command("close")
                    check("fixture no page errors", receipt["network"]["pageErrors"] == [])
                    check("no unexpected browser requests", receipt["network"]["blockedNetwork"] == 0)
                    browser.stdin.close()
                    check("browser clean exit", await asyncio.wait_for(browser.wait(), timeout=10) == 0)
        finally:
            if browser:
                if browser.returncode is None:
                    browser.stdin.close()
                    try:
                        await asyncio.wait_for(browser.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        browser.terminate()
                        await browser.wait()
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)
    receipt["pass"] = all(item["pass"] for item in receipt["checks"])
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = asyncio.run(run())
    if args.output:
        args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    raise SystemExit(0 if receipt["pass"] else 1)
