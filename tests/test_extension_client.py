"""Offline tests for stdio clients sharing the existing extension worker."""

import io
import json
import stat
import asyncio

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

    def open(self, request, timeout):
        body = request.data
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


@pytest.mark.parametrize("arguments", [{"job_id": "synthetic"}, {"job_id": "synthetic", "inspected_chatgpt": False}])
def test_mcp_resolve_requires_inspection_before_calling_client(arguments):
    from chatgpt_api.extension_bridge import create_mcp

    client = ExtensionClient(TOKEN)
    calls = []
    client.resolve = lambda job_id: calls.append(job_id) or {"state": "interrupted"}
    server = create_mcp(client)

    with pytest.raises(Exception, match="inspect ChatGPT"):
        asyncio.run(server.call_tool("extension_resolve", arguments))
    assert calls == []


def test_mcp_resolve_calls_client_only_after_explicit_inspection():
    from chatgpt_api.extension_bridge import create_mcp

    client = ExtensionClient(TOKEN)
    calls = []
    client.resolve = lambda job_id: calls.append(job_id) or {"state": "interrupted"}
    server = create_mcp(client)

    result = asyncio.run(server.call_tool("extension_resolve", {
        "job_id": "synthetic", "inspected_chatgpt": True,
    }))
    assert calls == ["synthetic"]
    assert "interrupted" in result[0].text


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


def test_connect_refuses_main_account_alias_before_touching_data(tmp_path, monkeypatch):
    missing = tmp_path / "must-stay-absent"
    monkeypatch.setattr("sys.argv", ["extension", "--account", "main", "--connect", "--data-dir", str(missing)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not missing.exists()
