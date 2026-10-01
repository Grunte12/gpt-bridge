import asyncio
import json
import sys

import pytest

pytest.importorskip("mcp")
from chatgpt_api.mcp_gateway import Gateway, create_server, http_app


def test_discovery_small_and_schema_on_demand(tmp_path):
    gateway = Gateway(tmp_path / "jobs", "main")
    brief = gateway.search("image")
    assert brief["tools"]
    assert all("input_schema" not in tool for tool in brief["tools"])
    assert all(not tool["name"].startswith("workspace.") for tool in gateway.search()["tools"])
    assert "input_schema" in gateway.search("image", "schema")["tools"][0]
    assert len(asyncio.run(create_server(gateway, []).list_tools())) == 3


def test_workspace_bounds_and_optimistic_replace(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.txt").write_text("before")
    gateway = Gateway(tmp_path / "jobs", "main", root)
    for value in ["../secret", ".env", ".git/config", "secrets/account"]:
        with pytest.raises(ValueError):
            gateway.workspace_path(value)
    (root / "escape").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError):
        gateway.workspace_path("escape")
    asyncio.run(gateway.call("workspace.replace", {"path": "app.txt", "old": "before", "new": "after"}))
    assert (root / "app.txt").read_text() == "after"
    with pytest.raises(ValueError):
        asyncio.run(gateway.call("workspace.replace", {"path": "app.txt", "old": "before", "new": "again"}))


def test_worker_argv_no_shell_and_server_owned_outputs(tmp_path):
    gateway = Gateway(tmp_path / "jobs", "main")
    argv = gateway.worker_argv("bridge.image", {"prompt": "$(touch /tmp/oops)", "transparent": True}, tmp_path / "output")
    assert "$(touch /tmp/oops)" in argv
    assert "--brief" in argv and "--transparent" in argv
    assert argv[argv.index("--output-path") + 1] == str(tmp_path / "output/image.png")
    with pytest.raises(Exception):
        asyncio.run(gateway.call("bridge.image", {"prompt": "x", "output_path": "/tmp/arbitrary"}))


def test_job_result_chunking_and_cancellation(tmp_path):
    async def scenario():
        gateway = Gateway(tmp_path / "jobs", "main", tmp_path, {
            "ok": [sys.executable, "-c", "print('hello')"],
            "slow": [sys.executable, "-c", "import time; time.sleep(60)"],
        })
        job = await gateway.call("workspace.test", {"name": "ok"})
        status = await gateway.status(job["job_id"], wait_seconds=10)
        assert status["state"] == "completed"
        assert "stderr.log" not in [a["name"] for a in status["artifacts"]]
        assert gateway.read_artifact(job["job_id"], "result.txt", limit=2)["data"] == "he"
        with pytest.raises(ValueError):
            gateway.read_artifact(job["job_id"], "../result.txt")
        job = await gateway.call("workspace.test", {"name": "slow"})
        await asyncio.sleep(0.05)
        assert (await gateway.status(job["job_id"], cancel=True))["state"] == "cancelled"
        assert not gateway.processes
    asyncio.run(scenario())


def test_http_requires_bearer_and_supports_mcp_initialize(tmp_path):
    from starlette.testclient import TestClient
    gateway = Gateway(tmp_path, "main")
    server = create_server(gateway, [])
    app = http_app(gateway, server, "x" * 32)
    with TestClient(app, base_url="http://localhost") as client:
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
        assert client.post("/mcp", json=body).status_code == 401
        response = client.post("/mcp", json=body, headers={"Authorization": "Bearer " + "x" * 32, "Accept": "application/json, text/event-stream"})
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "GPT Bridge"
        headers = {"Authorization": "Bearer " + "x" * 32, "Accept": "application/json, text/event-stream"}
        listing = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert len(listing.json()["result"]["tools"]) == 3
        call = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_tools", "arguments": {"query": "image", "detail": "schema"}}})
        assert not call.json()["result"].get("isError")
        assert "bridge.image" in json.dumps(call.json())
        gateway.jobs["demo"] = {"state": "completed"}
        (tmp_path / "demo").mkdir()
        (tmp_path / "demo/image.png").write_bytes(b"image-bytes")
        assert client.get("/artifacts/demo/image.png").status_code == 401
        assert client.get("/artifacts/demo/image.png", headers=headers).content == b"image-bytes"
        assert client.get("/artifacts/demo/stderr.log", headers=headers).status_code == 404
