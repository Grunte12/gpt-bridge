import json

import pytest

import chatgpt_api.cli as cli
from chatgpt_api.cli import main
from chatgpt_api.core.errors import ProviderError
from chatgpt_api.legacy_cli import translate_legacy_argv
from chatgpt_api.providers.chatgpt.crypto import is_encrypted
from chatgpt_api.providers.chatgpt.local_setup import LocalSetupResult
from chatgpt_api.worker.direct import DEFAULT_AGENT_MODEL, DirectWorkerClient, resolve_direct_account
from chatgpt_api.worker.client import WorkerClient, validate_worker_base_url, validate_worker_path
from chatgpt_api.worker.stack import compose_args
from chatgpt_api.worker.storage import default_worker_data_dir


def test_worker_client_is_loopback_only_and_preserves_v1_base():
    assert WorkerClient("http://127.0.0.1:8000/v1").url_for("/models") == "http://127.0.0.1:8000/v1/models"
    with pytest.raises(ProviderError, match="loopback"):
        validate_worker_base_url("https://example.com/v1")
    with pytest.raises(ProviderError, match="API-relative"):
        validate_worker_path("https://example.com/models")


def test_worker_defaults_map_legacy_bridge_environment(monkeypatch):
    monkeypatch.delenv("CHATGPT_BASE_URL", raising=False)
    monkeypatch.delenv("CHATGPT_API_KEY", raising=False)
    monkeypatch.setenv("BRIDGE_URL", "http://127.0.0.1:8012")
    monkeypatch.setenv("BRIDGE_TOKEN", "legacy-token")

    args = cli.build_parser().parse_args(["worker", "status"])

    assert args.base_url == "http://127.0.0.1:8012/v1"
    assert args.api_key == "legacy-token"
    assert args.transport == "direct"


def test_worker_agent_commands_default_to_verified_sol_high():
    parser = cli.build_parser()

    chat = parser.parse_args(["worker", "chat", "--message", "hello"])
    report = parser.parse_args(["worker", "report", "--prompt", "analyse this"])

    assert chat.model == DEFAULT_AGENT_MODEL
    assert report.model == DEFAULT_AGENT_MODEL
    assert chat.level is None


def test_worker_chat_instant_sets_fast_model_and_token_cap(monkeypatch, capsys):
    calls = []

    async def fake_api_request_json(args, method, path, body):
        calls.append(body)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(["worker", "chat", "--message", "hello", "--level", "instant", "--json"]) == 0

    assert calls[0]["model"] == "gpt-5-5"
    assert calls[0]["max_tokens"] == 1200


def test_worker_chat_reuses_router_and_worker_thread_location(tmp_path, monkeypatch, capsys):
    calls = []

    async def fake_api_request_json(args, method, path, body):
        calls.append((method, path, body))
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(["worker", "chat", "--message", "hello", "--thread", "job", "--threads-dir", str(tmp_path)]) == 0

    assert calls[0][1] == "/chat/completions"
    assert (tmp_path / "job.json").exists()
    assert "done" in capsys.readouterr().out


def test_worker_thread_commands_use_versioned_thread_files(tmp_path, capsys):
    assert main(["worker", "thread", "list", "--threads-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["threads"] == []

    state_path = tmp_path / "task.json"
    state_path.write_text(
        json.dumps({"version": 1, "name": "task", "compacted_summary": None, "messages": []}), encoding="utf-8"
    )
    assert main(["worker", "thread", "show", "task", "--threads-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "task"
    assert main(["worker", "thread", "clear", "task", "--threads-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cleared"] is True
    assert not state_path.exists()


def test_worker_web_primitives_list_export_and_continue(tmp_path, monkeypatch, capsys):
    conversation_id = "12345678-abcd-4321-abcd-1234567890ab"
    conversation = {
        "id": conversation_id,
        "title": "VS Code implementation brainstorm",
        "current_node": "assistant-1",
        "mapping": {
            "root": {"id": "root", "parent": None, "message": None},
            "user-1": {
                "id": "user-1",
                "parent": "root",
                "message": {
                    "id": "user-1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Design an adaptive bridge."]},
                },
            },
            "assistant-1": {
                "id": "assistant-1",
                "parent": "user-1",
                "message": {
                    "id": "assistant-1",
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "multimodal_text",
                        "parts": [
                            "Expose generic session primitives.",
                            {"content_type": "image_asset_pointer", "asset_pointer": "sediment://generated-diagram"},
                        ],
                    },
                },
            },
        },
    }

    class FakeWebClient:
        deleted = []

        async def list_web_conversations(self, **kwargs):
            assert kwargs == {"offset": 0, "limit": 20, "order": "updated"}
            return {"items": [{"id": conversation_id, "title": conversation["title"]}], "total": 1}

        async def get_web_conversation(self, requested):
            assert requested == conversation_id
            return conversation

        async def download_web_image(self, requested_conversation, asset_pointer):
            assert requested_conversation == conversation_id
            assert asset_pointer == "sediment://generated-diagram"
            return type(
                "Image",
                (),
                {"data": b"generated-image", "mime_type": "image/png"},
            )()

        async def send_web_message(self, **kwargs):
            assert kwargs["conversation_id"] == conversation_id
            assert kwargs["parent_message_id"] == "assistant-1"
            assert kwargs["message"] == "Turn this into an implementation handoff."
            return {
                "conversation_id": conversation_id,
                "parent_message_id": "assistant-1",
                "message_id": "assistant-2",
                "model": kwargs["model"],
                "provider_model": "gpt-5-6-thinking",
                "thinking_effort": "extended",
                "text": "Implementation handoff",
            }

        async def delete_web_conversation(self, requested_conversation):
            assert requested_conversation == conversation_id
            self.deleted.append(requested_conversation)
            return {
                "ok": True,
                "conversation_id": requested_conversation,
                "soft_deleted": True,
            }

    monkeypatch.setattr(cli, "_direct_web_client", lambda args: FakeWebClient())

    assert main(["worker", "web", "list", "--query", "vscode", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["conversations"][0]["id"] == conversation_id

    output = tmp_path / "brainstorm.md"
    assert main(
        [
            "worker",
            "web",
            "show",
            "--conversation",
            f"https://chatgpt.com/c/{conversation_id}",
            "--output",
            str(output),
            "--json",
        ]
    ) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["path"] == str(output.resolve())
    assert "generic session primitives" in output.read_text(encoding="utf-8")

    image_output = tmp_path / "latest.png"
    assert main(
        [
            "worker",
            "web",
            "pull",
            "--conversation",
            conversation_id,
            "--output-path",
            str(image_output),
            "--json",
        ]
    ) == 0
    pulled = json.loads(capsys.readouterr().out)
    assert pulled["assets"][0]["path"] == str(image_output.resolve())
    assert image_output.read_bytes() == b"generated-image"

    assert main(
        [
            "worker",
            "web",
            "send",
            "--conversation",
            conversation_id,
            "--message",
            "Turn this into an implementation handoff.",
            "--json",
        ]
    ) == 0
    continued = json.loads(capsys.readouterr().out)
    assert continued["text"] == "Implementation handoff"
    assert continued["message_id"] == "assistant-2"

    assert main(["worker", "web", "delete", "--conversation", conversation_id]) == 2
    assert "requires --yes" in capsys.readouterr().err

    assert main(
        [
            "worker",
            "web",
            "delete",
            "--conversation",
            conversation_id,
            "--yes",
            "--json",
        ]
    ) == 0
    deleted = json.loads(capsys.readouterr().out)
    assert deleted == {
        "object": "chatgpt.web.conversation.delete",
        "id": conversation_id,
        "soft_deleted": True,
        "ok": True,
    }
    assert FakeWebClient.deleted == [conversation_id]


def test_worker_report_preserves_model_authored_html_without_a_template(tmp_path, monkeypatch, capsys):
    calls = []

    async def fake_request_json(self, method, path, body=None):
        calls.append((method, path, body))
        return {
            "model": "auto",
            "choices": [{"message": {"content": "<!doctype html><html><body><canvas id='chart'></canvas></body></html>"}}],
        }

    monkeypatch.setattr(cli.WorkerClient, "request_json", fake_request_json)
    output = tmp_path / "analysis.html"

    assert main(
        [
            "worker",
            "--transport",
            "http",
            "report",
            "--prompt",
            "compare sales",
            "--title",
            "Sales",
            "--out",
            str(output),
            "--json",
        ]
    ) == 0

    assert output.read_text(encoding="utf-8") == "<!doctype html><html><body><canvas id='chart'></canvas></body></html>\n"
    assert calls[0][0:2] == ("POST", "/chat/completions")
    assert "standalone HTML" in calls[0][2]["messages"][0]["content"]
    assert json.loads(capsys.readouterr().out)["path"] == str(output.resolve())


def test_worker_migrate_wcbridge_copies_threads_without_touching_source(tmp_path, capsys):
    source = tmp_path / "legacy"
    destination = tmp_path / "new"
    source.mkdir()
    legacy_thread = source / "planning.json"
    legacy_thread.write_text(
        json.dumps(
            [
                {"role": "system", "content": "Keep it concise."},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
            ]
        ),
        encoding="utf-8",
    )

    assert main(
        ["worker", "migrate", "wcbridge", "--source-dir", str(source), "--threads-dir", str(destination), "--json"]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [{"name": "planning", "status": "migrated"}]
    assert json.loads(legacy_thread.read_text(encoding="utf-8"))[0]["content"] == "Keep it concise."
    migrated = json.loads((destination / "planning.json").read_text(encoding="utf-8"))
    assert migrated["compacted_summary"] == "Keep it concise."
    assert migrated["messages"] == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "answer"}]


def test_worker_stack_arguments_are_conservative():
    assert compose_args("up") == ["compose", "up", "-d", "gpt-bridge"]
    assert compose_args("down") == ["compose", "down"]
    assert "--build" not in compose_args("up")
    assert "-v" not in compose_args("down")


def test_legacy_executable_translates_the_supported_command_contract():
    assert translate_legacy_argv(["chat", "--message", "hi"]) == ["worker", "chat", "--message", "hi"]
    assert translate_legacy_argv(["image", "--prompt", "cat", "--out", "cat.png"]) == [
        "worker",
        "image",
        "--prompt",
        "cat",
        "--output-path",
        "cat.png",
    ]
    assert translate_legacy_argv(["raw", "GET", "/v1/models"]) == ["worker", "request", "/models", "--method", "GET"]


def test_worker_data_dir_uses_explicit_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATGPT_WORKER_DATA_DIR", str(tmp_path))
    assert default_worker_data_dir() == tmp_path


def test_direct_worker_resolves_exactly_one_capture(tmp_path):
    capture = tmp_path / "plus-main" / "chatgpt-request.txt"
    capture.parent.mkdir()
    capture.write_text("Request URL: https://chatgpt.com/backend-api/f/conversation\n", encoding="utf-8")

    assert resolve_direct_account(accounts_dir=tmp_path) == "plus-main"


def test_direct_worker_dispatches_chat_without_http(tmp_path, monkeypatch):
    capture = tmp_path / "plus-main" / "chatgpt-request.txt"
    capture.parent.mkdir()
    capture.write_text("Request URL: https://chatgpt.com/backend-api/f/conversation\n", encoding="utf-8")
    calls = []

    async def fake_chat_completion(config, body, router):
        calls.append((config, body, router))
        return {"model": body["model"], "choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr("chatgpt_api.worker.direct._chat_completion", fake_chat_completion)
    client = DirectWorkerClient(account="plus-main", accounts_dir=tmp_path)
    payload = cli.asyncio.run(
        client.request_json(
            "POST",
            "/chat/completions",
            {"model": DEFAULT_AGENT_MODEL, "messages": [{"role": "user", "content": "hello"}]},
        )
    )

    assert payload["choices"][0]["message"]["content"] == "done"
    assert calls[0][0].accounts == ("plus-main",)
    assert calls[0][0].model_fallback is None
    assert calls[0][1]["model"] == DEFAULT_AGENT_MODEL


def test_auth_import_validates_and_encrypts_capture_without_server(tmp_path, monkeypatch, capsys):
    capture_file = tmp_path / "capture.txt"
    capture_file.write_text(
        """
URL: https://chatgpt.com/backend-api/f/conversation
Authorization: Bearer fake-token
Cookie: oai-did=device-1; __Secure-next-auth.session-token.0=session-1
OpenAI-Sentinel-Chat-Requirements-Token: req-token
OpenAI-Sentinel-Proof-Token: proof-token
OpenAI-Sentinel-Turnstile-Token: turnstile-token
x-conduit-token: conduit-token
OAI-Device-Id: device-1
OAI-Session-Id: session-1
Request Data: {"action":"next","model":"gpt-5-6-thinking","thinking_effort":"extended"}
""".strip(),
        encoding="utf-8",
    )
    accounts_dir = tmp_path / "accounts"
    monkeypatch.setenv("CHATGPT_WORKER_DATA_DIR", str(tmp_path / "worker"))

    assert main(
        [
            "auth",
            "import",
            "--account",
            "main",
            "--accounts-dir",
            str(accounts_dir),
            "--capture-file",
            str(capture_file),
            "--json",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    encrypted = (accounts_dir / "main" / "chatgpt-request.txt").read_text(encoding="utf-8")
    assert payload["saved"] is True
    assert is_encrypted(encrypted)
    assert "fake-token" not in encrypted


def test_setup_captures_saves_and_verifies_without_server(tmp_path, monkeypatch, capsys):
    capture_text = """
URL: https://chatgpt.com/backend-api/f/conversation
Authorization: Bearer fake-token
Cookie: oai-did=device-1; __Secure-next-auth.session-token.0=session-1
OpenAI-Sentinel-Chat-Requirements-Token: req-token
OpenAI-Sentinel-Proof-Token: proof-token
OpenAI-Sentinel-Turnstile-Token: turnstile-token
x-conduit-token: conduit-token
OAI-Device-Id: device-1
OAI-Session-Id: session-1
Request Data: {"action":"next","model":"gpt-5-6-thinking","thinking_effort":"extended"}
""".strip()
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("CHATGPT_WORKER_DATA_DIR", str(tmp_path / "worker"))
    monkeypatch.setattr(
        cli,
        "capture_from_local_setup_page",
        lambda **kwargs: LocalSetupResult(capture_text=capture_text),
    )
    monkeypatch.setattr(cli, "_check_account_auth", lambda capture, impersonate: (200, True, None))

    assert main(["setup", "--account", "main", "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    capture_path = config_home / "gpt-bridge" / "accounts" / "main" / "chatgpt-request.txt"
    assert payload["ok"] is True
    assert payload["live_verify"]["auth_ok"] is True
    assert is_encrypted(capture_path.read_text(encoding="utf-8"))


def test_keyboard_interrupt_exits_cleanly_without_traceback(monkeypatch, capsys):
    async def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_setup", interrupted)

    assert main(["setup", "--yes"]) == 130
    stderr = capsys.readouterr().err
    assert "cancelled=true" in stderr
    assert "Traceback" not in stderr


def test_network_error_exits_cleanly_without_traceback(monkeypatch, capsys):
    async def failed(args):
        raise cli.CurlRequestException(
            "Failed to perform, curl: (6) Could not resolve host: chatgpt.com. "
            "See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
        )

    monkeypatch.setattr(cli, "cmd_setup", failed)

    assert main(["setup", "--yes"]) == 2
    stderr = capsys.readouterr().err
    assert stderr == "network error: Failed to perform, curl: (6) Could not resolve host: chatgpt.com.\n"
    assert "Traceback" not in stderr
