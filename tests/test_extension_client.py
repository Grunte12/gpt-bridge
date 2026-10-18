"""Offline tests for stdio clients sharing the existing extension worker."""

import io
import json
import stat
import asyncio
import base64
import subprocess
import sys
from PIL import Image

import pytest

from chatgpt_api.extension_bridge import (
    ExtensionClient,
    ExtensionQueue,
    NoRedirect,
    ProxyHandler,
    main,
    make_handler,
)


ACCOUNT = "second"
CLIENT_ID = "123e4567-e89b-12d3-a456-426614174000"
TOKEN = "synthetic-local-token-with-enough-length"
ORIGIN = "chrome-extension://" + "a" * 32


def _request(handler_type, path, payload, *, token=TOKEN, origin=ORIGIN,
             host="127.0.0.1:18767"):
    body = json.dumps(payload).encode()
    handler = object.__new__(handler_type)
    handler.headers = {
        "Host": host,
        "Origin": origin,
        "Authorization": f"Bearer {token}" if token else "",
        "Content-Length": str(len(body)),
    }
    handler.path = path
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    codes = []
    handler.send_response = codes.append
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    handler.do_POST()
    return codes[-1], json.loads(handler.wfile.getvalue())


def _private_token(path):
    path.write_text(TOKEN)
    path.chmod(0o600)


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, limit):
        return self.body[:limit]


class _LocalWorkerTransport:
    """Route a client Request into the handler without opening a socket."""

    def __init__(self, handler_type):
        self.handler_type = handler_type
        self.payloads = []

    def open(self, request, timeout):
        body = request.data
        self.payloads.append(json.loads(body))
        handler = object.__new__(self.handler_type)
        handler.headers = {
            "Host": "127.0.0.1:18767",
            "Origin": "",
            "Authorization": request.get_header("Authorization"),
            "Content-Length": str(len(body)),
        }
        handler.path = request.full_url.rsplit("/", 1)[-1]
        handler.path = "/agent/" + handler.path
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: setattr(handler, "status", code)
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        handler.do_POST()
        if handler.status >= 400:
            from urllib.error import HTTPError
            raise HTTPError(request.full_url, handler.status, "synthetic worker error", {}, None)
        return _Response(handler.wfile.getvalue())


def test_client_forwards_upload_clear_opt_in_and_omits_false_for_compatibility(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=3)
    handler = make_handler(queue, TOKEN, 18767)
    client = ExtensionClient(TOKEN)
    transport = _LocalWorkerTransport(handler)
    client.http = transport

    default = client.submit("Check without clearing.", "Create image", preflight_only=True)
    assert "clear_preflight_uploads" not in transport.payloads[-1]
    queue.claim(CLIENT_ID)
    default_receipt = queue.result(CLIENT_ID, default["job_id"], preflight_ready=True)
    assert "preflight_uploads_cleared" not in default_receipt

    cleared = client.submit(
        "Check and clear the verified upload.",
        "Create image",
        preflight_only=True,
        clear_preflight_uploads=True,
    )
    assert transport.payloads[-1]["clear_preflight_uploads"] is True
    claimed = queue.claim(CLIENT_ID)
    assert claimed["clear_preflight_uploads"] is True
    receipt = queue.result(
        CLIENT_ID,
        cleared["job_id"],
        preflight_ready=True,
        preflight_uploads_cleared=True,
    )
    assert receipt["preflight_uploads_cleared"] is True

    before = len(queue.jobs)
    with pytest.raises(ValueError, match="No automatic retry"):
        client.submit(
            "Invalid flag is passed through for worker validation.",
            "Create image",
            preflight_only=True,
            clear_preflight_uploads=0,
        )
    assert transport.payloads[-1]["clear_preflight_uploads"] == 0
    assert len(queue.jobs) == before


def test_client_resolve_propagates_clear_flag_only_when_true():
    client = ExtensionClient(TOKEN)
    calls = []
    client.call = lambda action, payload: calls.append((action, payload)) or {"state": "queued"}

    client.resolve("synthetic-job")
    client.resolve("synthetic-job", clear_preflight_uploads=False)
    client.resolve("synthetic-job", clear_preflight_uploads=True)
    client.resolve("synthetic-job", recover_outputs=True,
                   recovery_chat_path="/c/123e4567-e89b-12d3-a456-426614174000")

    assert calls == [
        ("resolve", {"job_id": "synthetic-job", "inspected_chatgpt": True}),
        ("resolve", {"job_id": "synthetic-job", "inspected_chatgpt": True}),
        ("resolve", {"job_id": "synthetic-job", "inspected_chatgpt": True,
                      "clear_preflight_uploads": True}),
        ("resolve", {"job_id": "synthetic-job", "inspected_chatgpt": True,
                      "recover_outputs": True,
                      "recovery_chat_path": "/c/123e4567-e89b-12d3-a456-426614174000"}),
    ]


def test_two_stdio_clients_share_the_worker_queue_and_only_one_claims(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image")
    handler = make_handler(queue, TOKEN, 18767)
    first = ExtensionClient(TOKEN)
    second = ExtensionClient(TOKEN)
    first.http = second.http = _LocalWorkerTransport(handler)

    job = first.submit("Synthetic test image", "Create image")
    assert job["state"] == "queued"
    assert first.token == second.token == TOKEN
    claimed_status, claimed = _request(handler, "/next", {"client_id": CLIENT_ID})
    assert claimed_status == 200
    assert claimed["job_id"] == job["job_id"]
    assert _request(handler, "/next", {"client_id": CLIENT_ID}) == (200, {})
    assert second.status(job["job_id"])["state"] == "claimed"


def test_confirm_delete_client_proxies_explicit_owner_approval_to_shared_worker(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image")
    handler = make_handler(queue, TOKEN, 18767)
    client = ExtensionClient(TOKEN)
    client.http = _LocalWorkerTransport(handler)
    submitted = client.submit("One saved image.", "Create image")
    queue.claim(CLIENT_ID)
    image = Image.new("RGB", (512, 512), (40, 90, 180))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                 cleanup_pending=True, chat_path="/c/123e4567-e89b-12d3-a456-426614174000")
    queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")

    approved = client.confirm_delete(submitted["job_id"], owner_confirmed=True)
    assert approved["cleanup_confirmation"] == "requested"
    with pytest.raises(ValueError, match="No automatic retry"):
        client.confirm_delete(submitted["job_id"], owner_confirmed=False)


def test_worker_enforces_one_active_image_even_across_clients(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image")
    handler = make_handler(queue, TOKEN, 18767)
    assert _request(handler, "/agent/image", {
        "prompt": "First synthetic image", "expected_model": "Create image",
    }, origin="")[0] == 200
    status, _ = _request(handler, "/agent/image", {
        "prompt": "Do not duplicate", "expected_model": "Create image",
    }, origin="")
    assert status == 400
    assert len(queue.jobs) == 1


def test_agent_routes_require_auth_valid_origin_and_operator_confirmation(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image")
    handler = make_handler(queue, TOKEN, 18767)
    assert _request(handler, "/agent/status", {}, token="wrong", origin="")[0] == 401
    assert _request(handler, "/agent/status", {}, origin="https://example.com")[0] == 403
    assert _request(handler, "/agent/status", {}, host="evil.example")[0] == 403

    submitted = queue.submit("Synthetic unresolved job", "Create image")
    assert _request(handler, "/agent/resolve", {"job_id": submitted["job_id"]}, origin="")[0] == 400
    assert _request(handler, "/agent/resolve", {
        "job_id": submitted["job_id"], "inspected_chatgpt": 1,
    }, origin="")[0] == 400
    assert queue.status(submitted["job_id"])["state"] == "queued"
    resolved_status, resolved = _request(handler, "/agent/resolve", {
        "job_id": submitted["job_id"], "inspected_chatgpt": True,
    }, origin="")
    assert resolved_status == 200
    assert resolved["state"] == "interrupted"


@pytest.mark.parametrize("failure", ["timeout", "connection", "http", "bad-json", "oversized", "non-object"])
def test_extension_client_failure_is_single_attempt_and_never_retried(monkeypatch, failure):
    calls = []

    class FakeHTTP:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout))
            if failure == "timeout":
                raise TimeoutError("synthetic timeout")
            if failure == "connection":
                raise OSError("synthetic connection failure")
            if failure == "http":
                from urllib.error import HTTPError
                raise HTTPError(request.full_url, 503, "synthetic", {}, None)

            class Response:
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    pass
                def read(self, _):
                    if failure == "oversized":
                        return b" " * (128 * 1024 + 1)
                    if failure == "non-object":
                        return b"[]"
                    return b"not-json"
            return Response()

    client = ExtensionClient(TOKEN)
    client.http = FakeHTTP()
    with pytest.raises(ValueError, match="No automatic retry"):
        client.submit("Synthetic only", "Create image")
    assert len(calls) == 1


def test_client_opener_disables_redirects_and_environment_proxies(monkeypatch):
    captured = []
    monkeypatch.setattr("chatgpt_api.extension_bridge.build_opener", lambda *handlers: captured.extend(handlers))
    ExtensionClient(TOKEN)
    proxy_handler, redirect_handler = captured
    assert isinstance(proxy_handler, ProxyHandler)
    assert proxy_handler.proxies == {}
    assert isinstance(redirect_handler, NoRedirect)
    assert redirect_handler.redirect_request(None, None, None, None, None, None) is None


@pytest.mark.parametrize("arguments", [
    {"job_id": "synthetic"},
    {"job_id": "synthetic", "inspected_chatgpt": False},
])
def test_mcp_resolve_requires_inspection_before_calling_client(arguments):
    from chatgpt_api.extension_bridge import create_mcp

    client = ExtensionClient(TOKEN)
    calls = []
    client.resolve = lambda job_id, clear_preflight_uploads=False: calls.append(
        (job_id, clear_preflight_uploads)
    ) or {"state": "interrupted"}
    server = create_mcp(client)

    with pytest.raises(Exception, match="inspect ChatGPT"):
        asyncio.run(server.call_tool("resolve", arguments))
    assert calls == []


@pytest.mark.parametrize("arguments", [
    {"job_id": "synthetic", "inspected_chatgpt": 1},
    {"job_id": "synthetic", "inspected_chatgpt": "true"},
    {"job_id": "synthetic", "inspected_chatgpt": True, "clear_preflight_uploads": 1},
    {"job_id": "synthetic", "inspected_chatgpt": True, "clear_preflight_uploads": "true"},
    {"job_id": "synthetic", "inspected_chatgpt": True, "clear_failed_uploads": 1},
    {"job_id": "synthetic", "inspected_chatgpt": True, "clear_failed_uploads": "true"},
    {"job_id": "synthetic", "inspected_chatgpt": True, "recover_outputs": 1},
    {"job_id": "synthetic", "inspected_chatgpt": True, "recover_outputs": "true"},
    {"job_id": "synthetic", "inspected_chatgpt": True, "recover_outputs": True, "recovery_chat_path": 123},
])
def test_mcp_resolve_rejects_non_boolean_inspection_and_cleanup_flags(arguments):
    from chatgpt_api.extension_bridge import create_mcp

    client = ExtensionClient(TOKEN)
    calls = []
    client.resolve = lambda job_id, clear_preflight_uploads=False: calls.append(
        (job_id, clear_preflight_uploads)
    ) or {"state": "queued"}
    server = create_mcp(client)

    with pytest.raises(Exception):
        asyncio.run(server.call_tool("resolve", arguments))
    assert calls == []


def test_mcp_resolve_calls_client_only_after_explicit_inspection():
    from chatgpt_api.extension_bridge import create_mcp

    client = ExtensionClient(TOKEN)
    calls = []
    client.resolve = lambda job_id, clear_preflight_uploads=False: calls.append(
        (job_id, clear_preflight_uploads)
    ) or {"state": "interrupted"}
    server = create_mcp(client)

    result = asyncio.run(server.call_tool("resolve", {
        "job_id": "synthetic", "inspected_chatgpt": True,
    }))
    assert calls == [("synthetic", False)]
    assert "interrupted" in result[0].text

    result = asyncio.run(server.call_tool("resolve", {
        "job_id": "synthetic", "inspected_chatgpt": True, "clear_preflight_uploads": True,
    }))
    assert calls == [("synthetic", False), ("synthetic", True)]
    assert "interrupted" in result[0].text


def test_mcp_failed_upload_cleanup_forwards_only_explicit_inspected_names():
    from chatgpt_api.extension_bridge import create_mcp

    client = ExtensionClient(TOKEN)
    calls = []
    client.resolve = lambda *args: calls.append(args) or {"state": "queued"}
    server = create_mcp(client)
    names = ["input-001(1).png", "input-002(1).png"]
    asyncio.run(server.call_tool("resolve", {
        "job_id": "synthetic", "inspected_chatgpt": True,
        "clear_failed_uploads": True, "native_upload_names": names,
    }))
    assert calls == [("synthetic", False, True, names)]


def test_mcp_output_recovery_forwards_explicit_chat_path_after_inspection():
    from chatgpt_api.extension_bridge import create_mcp

    client = ExtensionClient(TOKEN)
    calls = []
    client.resolve = lambda *args: calls.append(args) or {"state": "queued"}
    server = create_mcp(client)
    chat_path = "/c/123e4567-e89b-12d3-a456-426614174000"

    result = asyncio.run(server.call_tool("resolve", {
        "job_id": "synthetic-job",
        "inspected_chatgpt": True,
        "recover_outputs": True,
        "recovery_chat_path": chat_path,
    }))

    assert calls == [("synthetic-job", False, False, None, True, chat_path)]
    assert "queued" in result[0].text


def test_mcp_exposes_fourth_confirm_delete_tool_and_requires_true_owner_approval(tmp_path):
    from chatgpt_api.extension_bridge import create_mcp

    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image")
    submitted = queue.submit("MCP delete test.", "Create image")
    queue.claim(CLIENT_ID)
    image = Image.new("RGB", (512, 512), (40, 90, 180))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=base64.b64encode(buffer.getvalue()).decode(),
                 cleanup_pending=True, chat_path="/c/123e4567-e89b-12d3-a456-426614174000")
    queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")
    server = create_mcp(queue)
    tools = server._tool_manager.list_tools()
    assert {tool.name for tool in tools} == {
        "status", "generate", "edit", "wait", "confirm_delete", "resolve",
    }

    with pytest.raises(Exception, match="actual owner confirmation"):
        asyncio.run(server.call_tool("confirm_delete", {
            "job_id": submitted["job_id"], "owner_confirmed": False,
        }))
    result = asyncio.run(server.call_tool("confirm_delete", {
        "job_id": submitted["job_id"], "owner_confirmed": True,
    }))
    assert "requested" in result[0].text


def test_connect_mode_uses_existing_token_without_queue_or_listener(tmp_path, monkeypatch):
    data_dir = tmp_path / "existing"
    data_dir.mkdir(mode=0o700)
    token_file = data_dir / "extension-token"
    _private_token(token_file)
    before = {p.name: (p.stat().st_mode, p.read_bytes()) for p in data_dir.iterdir()}
    constructed = []

    class Client:
        def __init__(self, token):
            constructed.append(token)

    class MCP:
        def run(self, *, transport):
            assert transport == "stdio"

    monkeypatch.setattr("sys.argv", ["extension", "--account", "second", "--connect", "--data-dir", str(data_dir)])
    monkeypatch.setattr("chatgpt_api.extension_bridge.ExtensionClient", Client)
    monkeypatch.setattr("chatgpt_api.extension_bridge.create_mcp", lambda client: MCP())
    monkeypatch.setattr("chatgpt_api.extension_bridge.ExtensionQueue", lambda *_: pytest.fail("created a queue"))
    monkeypatch.setattr("chatgpt_api.extension_bridge.ThreadingHTTPServer", lambda *_: pytest.fail("created listener"))

    main()

    assert constructed == [TOKEN]
    after = {p.name: (p.stat().st_mode, p.read_bytes()) for p in data_dir.iterdir()}
    assert after == before
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_connect_exits_when_stdin_is_already_closed(tmp_path):
    root = tmp_path / "existing"
    root.mkdir(mode=0o700)
    _private_token(root / "extension-token")
    process = subprocess.Popen(
        [sys.executable, "-m", "chatgpt_api.extension_bridge", "--account", "second", "--connect",
         "--data-dir", str(root)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise
    assert process.returncode is not None


def test_serve_mode_keeps_worker_alive_without_stdio_mcp(tmp_path, monkeypatch):
    root = tmp_path / "existing"
    root.mkdir(mode=0o700)
    _private_token(root / "extension-token")
    calls = []

    class HTTP:
        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 18767)

        def serve_forever(self):
            calls.append("serve")

        def server_close(self):
            calls.append("close")

    monkeypatch.setattr("sys.argv", ["extension", "--account", "second", "--serve",
                                     "--data-dir", str(root)])
    monkeypatch.setattr("chatgpt_api.extension_bridge.ThreadingHTTPServer", HTTP)
    monkeypatch.setattr("chatgpt_api.extension_bridge.create_mcp",
                        lambda *_: pytest.fail("started stdio MCP in background mode"))
    monkeypatch.setattr("chatgpt_api.extension_bridge.threading.Thread",
                        lambda **_: pytest.fail("started disposable HTTP thread"))
    main()
    assert calls == ["serve", "close"]


def test_serve_and_connect_are_mutually_exclusive_before_touching_data(tmp_path, monkeypatch):
    missing = tmp_path / "must-stay-absent"
    monkeypatch.setattr("sys.argv", ["extension", "--account", "second", "--serve", "--connect",
                                     "--data-dir", str(missing)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not missing.exists()


def test_connect_refuses_main_account_alias_before_touching_data(tmp_path, monkeypatch):
    missing = tmp_path / "must-stay-absent"
    monkeypatch.setattr("sys.argv", ["extension", "--account", "main", "--connect", "--data-dir", str(missing)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not missing.exists()


def test_connect_rejects_auto_cleanup_policy_before_reading_token_or_starting_worker(tmp_path, monkeypatch):
    data_dir = tmp_path / "must-stay-absent"
    monkeypatch.setattr("sys.argv", [
        "extension", "--account", "second", "--connect", "--auto-delete-saved-chats",
        "--data-dir", str(data_dir),
    ])
    monkeypatch.setattr("chatgpt_api.extension_bridge.read_token", lambda *_: pytest.fail("read token"))
    monkeypatch.setattr("chatgpt_api.extension_bridge.ExtensionClient", lambda *_: pytest.fail("created client"))
    monkeypatch.setattr("chatgpt_api.extension_bridge.ExtensionQueue", lambda *_: pytest.fail("created queue"))
    monkeypatch.setattr("chatgpt_api.extension_bridge.ThreadingHTTPServer", lambda *_: pytest.fail("started worker"))

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert not data_dir.exists()
