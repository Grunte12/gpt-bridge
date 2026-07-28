import argparse
import json
from pathlib import Path

import chatgpt_api.cli as cli
from chatgpt_api.cli import main
from chatgpt_api.core.errors import ProviderError
from chatgpt_api.core.types import ChatDelta, ImageAsset, ImageResponse
from chatgpt_api.providers.chatgpt.crypto import (
    clear_runtime_passphrase,
    decrypt_text,
    encrypt_text,
    is_encrypted,
    key_file_path,
    load_auto_secrets_key,
    load_secrets_key,
    set_runtime_passphrase,
)


def test_inspect_capture_redacts_secret_headers(tmp_path, capsys):
    capture_path = tmp_path / "request.txt"
    capture_path.write_text(
        """
URL: https://chatgpt.com/backend-api/f/conversation
Authorization: Bearer fake-token
Cookie: oai-did=device-1
Accept: text/event-stream
""",
        encoding="utf-8",
    )

    exit_code = main(["inspect-capture", str(capture_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "authorization: <redacted>" in output
    assert "cookie: <redacted>" in output
    assert "fake-token" not in output


def test_inspect_capture_from_account_profile(tmp_path, capsys):
    capture_path = tmp_path / "pro" / "chatgpt-request.txt"
    capture_path.parent.mkdir()
    capture_path.write_text(
        """
URL: https://chatgpt.com/backend-api/f/conversation
Authorization: Bearer fake-token
Request Data: {"action":"next"}
""",
        encoding="utf-8",
    )

    exit_code = main(["inspect-capture", "--account", "pro", "--accounts-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "request_json=yes" in output
    assert "fake-token" not in output


def test_accounts_lists_profiles(tmp_path, capsys):
    (tmp_path / "free").mkdir()
    (tmp_path / "free" / "chatgpt-request.txt").write_text("URL: https://chatgpt.com\n", encoding="utf-8")

    exit_code = main(["accounts", "--accounts-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "free: capture=yes" in output


def test_auth_status_reports_only_non_secret_local_state(tmp_path, capsys):
    capture_path = tmp_path / "main" / "chatgpt-request.txt"
    capture_path.parent.mkdir()
    key = load_secrets_key(tmp_path)
    capture_path.write_text(encrypt_text("Authorization: Bearer private-token", key), encoding="utf-8")

    exit_code = main(["auth", "status", "--accounts-dir", str(tmp_path), "--json"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"account": "main"' in output
    assert '"encrypted": true' in output
    assert "private-token" not in output


def test_auth_login_requires_explicit_consent_outside_an_interactive_terminal(tmp_path, capsys):
    exit_code = main(
        [
            "auth",
            "login",
            "--account",
            "main",
            "--accounts-dir",
            str(tmp_path),
            "--base-url",
            "http://127.0.0.1:9/v1",
            "--api-key",
            "test-key",
            "--json",
        ]
    )

    assert exit_code == 2
    assert "needs --yes" in capsys.readouterr().err


def test_gpt_bridge_parser_uses_the_memorable_command_name():
    assert cli.build_parser(prog="gpt-bridge").prog == "gpt-bridge"


def test_doctor_json_reports_missing_setup_without_crashing(tmp_path, capsys):
    exit_code = main(
        [
            "doctor",
            "--json",
            "--accounts-dir",
            str(tmp_path),
            "--base-url",
            "http://127.0.0.1:9/v1",
            "--api-key",
            "test-local-key",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert '"object": "chatgpt.doctor"' in output
    assert '"account_profiles"' in output
    assert "test-local-key" not in output


def test_server_command_prints_start_command(capsys):
    exit_code = main(["server", "command", "--preset", "local", "--api-key", "test-local-key"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "gpt-bridge server start" in output
    assert "--accounts" not in output
    assert "test-local-key" in output


def test_serve_concise_system_prompt_flag_and_environment(monkeypatch):
    parser = cli.build_parser()

    assert parser.parse_args(["serve", "--no-concise-system-prompt"]).concise_system_prompt is False
    monkeypatch.setenv("CHATGPT_CONCISE_SYSTEM_PROMPT", "false")
    assert cli.build_parser().parse_args(["serve"]).concise_system_prompt is False


def test_serve_rejects_the_known_insecure_default_key(capsys):
    assert main(["serve", "--api-key", "local-dev-key"]) == 2
    assert "local-dev-key is not allowed" in capsys.readouterr().err


def test_server_command_keeps_explicit_account_pool(capsys):
    exit_code = main(["server", "command", "--preset", "local", "--accounts", "go,plus-main", "--api-key", "test-local-key"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "--accounts go,plus-main" in output


def test_server_command_accepts_launch_overrides(capsys):
    exit_code = main(
        [
            "server",
            "command",
            "--preset",
            "local",
            "--api-key",
            "test-local-key",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
            "--public-base-url",
            "http://127.0.0.1:8010/v1",
            "--account-strategy",
            "random",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "--account-strategy random" in output
    assert "--port 8010" in output
    assert "--public-base-url http://127.0.0.1:8010/v1" in output


def test_server_accounts_auto_discovers_saved_captures(tmp_path):
    for name in ("go", "plus-main"):
        capture = tmp_path / name / "chatgpt-request.txt"
        capture.parent.mkdir()
        capture.write_text("URL: https://chatgpt.com/backend-api/f/conversation\n", encoding="utf-8")

    args = argparse.Namespace(accounts="", account="", accounts_dir=tmp_path)

    assert cli._server_accounts_from_args(args) == ("go", "plus-main")
    assert cli._primary_account_from_args(args, ("go", "plus-main")) == "go"


def test_server_accounts_can_be_pinned_to_skip_broken_profiles(tmp_path):
    for name in ("broken-old", "plus"):
        capture = tmp_path / name / "chatgpt-request.txt"
        capture.parent.mkdir()
        capture.write_text("URL: https://chatgpt.com/backend-api/f/conversation\n", encoding="utf-8")

    args = argparse.Namespace(accounts="plus", account="", accounts_dir=tmp_path)

    assert cli._server_accounts_from_args(args) == ("plus",)


def test_server_command_docker_accounts_mount_is_writable(capsys):
    exit_code = main(["server", "command", "--preset", "docker"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "/data/secrets/accounts:ro" not in output
    assert "-v \"$PWD/secrets/accounts:/data/secrets/accounts\"" in output


def test_api_chat_posts_route_override_to_bridge_router(monkeypatch, capsys):
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        return {
            "id": "chatcmpl_test",
            "model": body["model"],
            "chatgpt_account": "pro",
            "choices": [{"message": {"content": "ok from router"}}],
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    exit_code = main(
        [
            "api",
            "chat",
            "--message",
            "hello",
            "--model",
            "auto",
            "--account",
            "pro",
            "--temporary-chat",
            "--agent-mode",
            "opencode",
            "--preset",
            "structured",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["method"] == "POST"
    assert calls["path"] == "/chat/completions"
    assert calls["body"]["chatgpt_account"] == "pro"
    assert calls["body"]["metadata"]["chatgpt_temporary_chat"] is True
    assert calls["body"]["metadata"]["agent_mode"] == "opencode"
    assert calls["body"]["metadata"]["chatgpt_preset"] == "structured"
    assert "ok from router" in output


def test_direct_chat_resolves_preset_locally(monkeypatch, capsys):
    seen = {}

    class FakeProvider:
        async def stream_chat(self, request):
            seen["messages"] = request.messages
            return
            yield

    monkeypatch.setattr(cli, "_provider_from_chat_args", lambda args, capture_path: FakeProvider())

    assert main(["chat", "--message", "hello", "--preset", "thai-content"]) == 0
    assert seen["messages"][0].role == "system"
    assert "natural, polished Thai" in seen["messages"][0].content[0].text


def test_api_image_saves_locally_without_sending_host_output_path(tmp_path, monkeypatch, capsys):
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        return {
            "id": "img_test",
            "model": body["model"],
            "chatgpt_account": "pro",
            "data": [
                {
                    "b64_json": "cG5nLWJ5dGVz",
                    "mime_type": "image/png",
                    "path": "/data/outputs/generated.png",
                }
            ],
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    output_dir = tmp_path / "local-images"

    exit_code = main(
        [
            "api",
            "image",
            "--prompt",
            "make one image",
            "--account",
            "pro",
            "--output-dir",
            str(output_dir),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["method"] == "POST"
    assert calls["path"] == "/images/generations"
    assert "output_dir" not in calls["body"]
    assert "output_path" not in calls["body"]
    assert calls["body"]["chatgpt_account"] == "pro"
    saved = output_dir / "generated.png"
    assert saved.read_bytes() == b"png-bytes"
    assert f"local_path[1]={saved.resolve()}" in output


def test_api_image_enhancement_uses_expanded_prompt_and_surfaces_it(monkeypatch, capsys):
    calls = []

    async def fake_api_request_json(args, method, path, body):
        calls.append((path, body))
        if path == "/chat/completions":
            assert body["messages"][0]["role"] == "system"
            return {"choices": [{"message": {"content": "expanded cinematic prompt"}}]}
        assert body["prompt"] == "expanded cinematic prompt"
        return {"data": [{"url": "https://example.test/image.png"}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(["api", "image", "--prompt", "a cat", "--enhance", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [path for path, _body in calls] == ["/chat/completions", "/images/generations"]
    assert payload["chatgpt_enhancement_applied"] is True
    assert payload["chatgpt_enhanced_prompt"] == "expanded cinematic prompt"


def test_api_image_default_makes_only_one_generation_request(monkeypatch, capsys):
    calls = []

    async def fake_api_request_json(args, method, path, body):
        calls.append((path, body))
        return {"data": [{"url": "https://example.test/image.png"}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(["api", "image", "--prompt", "a concise production prompt", "--json"]) == 0
    assert [path for path, _body in calls] == ["/images/generations"]
    assert json.loads(capsys.readouterr().out)["data"][0]["url"] == "https://example.test/image.png"


def test_worker_image_brief_returns_output_and_reusable_web_session(tmp_path, monkeypatch, capsys):
    output = tmp_path / "draft.png"
    conversation_id = "12345678-abcd-4321-abcd-1234567890ab"

    async def fake_api_request_json(args, method, path, body):
        return {
            "model": body["model"],
            "chatgpt_operation_id": "image-operation",
            "chatgpt_conversation_id": conversation_id,
            "chatgpt_web_url": f"https://chatgpt.com/c/{conversation_id}",
            "data": [
                {
                    "url": "/v1/files/generated/content",
                    "path": str(output),
                    "file_id": "large-internal-id",
                }
            ],
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(["worker", "--transport", "http", "image", "--prompt", "draft", "--brief"]) == 0
    assert capsys.readouterr().out == (
        f'{{"ok":true,"outputs":[{{"path":"{output}"}}],'
        f'"conversation":{{"id":"{conversation_id}","web_url":"https://chatgpt.com/c/{conversation_id}"}}}}\n'
    )


def test_worker_image_cleanup_soft_deletes_only_after_local_save(tmp_path, monkeypatch, capsys):
    output = tmp_path / "one-shot.png"
    conversation_id = "12345678-abcd-4321-abcd-1234567890ab"
    deleted = []

    async def fake_api_request_json(args, method, path, body):
        return {
            "chatgpt_conversation_id": conversation_id,
            "data": [{"b64_json": "cG5nLWJ5dGVz", "mime_type": "image/png"}],
        }

    class FakeWebClient:
        async def delete_web_conversation(self, requested_conversation):
            assert output.read_bytes() == b"png-bytes"
            deleted.append(requested_conversation)
            return {
                "ok": True,
                "conversation_id": requested_conversation,
                "soft_deleted": True,
            }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    monkeypatch.setattr(cli, "_direct_web_client", lambda args: FakeWebClient())

    assert main(
        [
            "worker",
            "image",
            "--prompt",
            "one-shot image",
            "--output-path",
            str(output),
            "--cleanup-session",
            "--brief",
        ]
    ) == 0

    assert deleted == [conversation_id]
    assert capsys.readouterr().out == (
        f'{{"ok":true,"outputs":[{{"path":"{output.resolve()}"}}],"session_cleanup":"soft_deleted"}}\n'
    )


def test_worker_image_cleanup_keeps_session_when_output_is_not_saved(monkeypatch, capsys):
    conversation_id = "12345678-abcd-4321-abcd-1234567890ab"
    deleted = []

    async def fake_api_request_json(args, method, path, body):
        return {
            "chatgpt_conversation_id": conversation_id,
            "data": [{"url": "https://example.test/generated.png"}],
        }

    class FakeWebClient:
        async def delete_web_conversation(self, requested_conversation):
            deleted.append(requested_conversation)
            return {"ok": True, "soft_deleted": True}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    monkeypatch.setattr(cli, "_direct_web_client", lambda args: FakeWebClient())

    assert main(
        [
            "worker",
            "image",
            "--prompt",
            "one-shot image",
            "--cleanup-session",
            "--brief",
        ]
    ) == 2

    assert deleted == []
    assert "requires --output-path or --output-dir" in capsys.readouterr().err


def test_worker_image_transparent_adds_matte_contract_and_verifies_alpha(tmp_path, monkeypatch, capsys):
    output = tmp_path / "asset.png"
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["body"] = body
        return {"data": [{"b64_json": "ZmFrZS1pbWFnZQ==", "mime_type": "image/png"}]}

    def fake_ensure_transparent_png(source, destination):
        assert source == output
        assert destination == output
        return {
            "ok": True,
            "path": str(output),
            "already_transparent": False,
            "transparent_pixels": 100,
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    monkeypatch.setattr(cli, "ensure_transparent_png", fake_ensure_transparent_png)

    assert main(
        [
            "worker",
            "--transport",
            "http",
            "image",
            "--prompt",
            "isolated leaf",
            "--output-path",
            str(output),
            "--transparent",
            "--brief",
        ]
    ) == 0
    assert "truly transparent alpha" in calls["body"]["prompt"]
    assert "#FF00FF" in calls["body"]["prompt"]
    assert capsys.readouterr().out == f'{{"ok":true,"outputs":[{{"path":"{output}"}}]}}\n'


def test_worker_image_transparent_requires_png_output_path(capsys):
    assert main(["worker", "image", "--prompt", "asset", "--transparent"]) == 2
    assert "requires --output-path" in capsys.readouterr().err


def test_worker_edit_brief_returns_only_output_location(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    output = tmp_path / "edited.png"
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["path"] = path
        calls["body"] = body
        return {"data": [{"path": str(output), "file_id": "large-internal-id"}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(
        [
            "worker",
            "--transport",
            "http",
            "edit",
            "--prompt",
            "Change only the background",
            "--input-image",
            str(source),
            "--brief",
        ]
    ) == 0
    assert calls["path"] == "/images/edits"
    assert calls["body"]["input_images"][0]["name"] == "source.png"
    assert capsys.readouterr().out == (
        f'{{"ok":true,"outputs":[{{"path":"{output}"}}]}}\n'
    )


def test_worker_edit_rejects_more_than_ten_inputs(tmp_path, capsys):
    argv = ["worker", "edit", "--prompt", "composite", "--brief"]
    for index in range(11):
        source = tmp_path / f"source-{index}.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        argv.extend(["--input-image", str(source)])

    assert main(argv) == 2
    assert "requires 1 to 10" in capsys.readouterr().err


def test_api_image_enhancement_failure_uses_raw_prompt_with_visible_warning(monkeypatch, capsys):
    async def fake_api_request_json(args, method, path, body):
        if path == "/chat/completions":
            raise ProviderError("enhancer unavailable")
        assert body["prompt"] == "a cat"
        return {"data": [{"url": "https://example.test/image.png"}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(["api", "image", "--prompt", "a cat", "--enhance", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chatgpt_enhancement_applied"] is False
    assert "enhancer unavailable" in payload["chatgpt_enhancement_error"]


def test_direct_image_enhancement_uses_expanded_prompt(monkeypatch, capsys):
    class FakeProvider:
        async def stream_chat(self, request):
            yield ChatDelta(text="expanded direct prompt")

        async def generate_image(self, request):
            assert request.prompt == "expanded direct prompt"
            return ImageResponse(images=[ImageAsset(url="https://example.test/image.png")], prompt=request.prompt)

    monkeypatch.setattr(cli, "_provider_from_chat_args", lambda args, capture_path: FakeProvider())

    assert main(["image", "--prompt", "a cat", "--enhance"]) == 0
    assert "prompt_enhancement=applied" in capsys.readouterr().out


def test_api_image_enhancement_rejects_artifact_response(monkeypatch, capsys):
    calls = []

    async def fake_api_request_json(args, method, path, body):
        calls.append((path, body))
        if path == "/chat/completions":
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Image generated.\nSaved files:\n/Users/test/generated_images/wrong.png"
                        }
                    }
                ]
            }
        assert body["prompt"] == "a precise architecture diagram"
        return {"data": [{"url": "https://example.test/image.png"}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(
        [
            "api",
            "image",
            "--prompt",
            "a precise architecture diagram",
            "--enhance",
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [path for path, _body in calls] == ["/chat/completions", "/images/generations"]
    assert payload["chatgpt_enhancement_applied"] is False
    assert "artifact response" in payload["chatgpt_enhancement_error"]


def test_direct_image_enhancement_rejects_file_path(monkeypatch, capsys):
    class FakeProvider:
        async def stream_chat(self, request):
            yield ChatDelta(text="/Users/test/generated_images/wrong.png")

        async def generate_image(self, request):
            assert request.prompt == "a cat"
            return ImageResponse(images=[ImageAsset(url="https://example.test/image.png")], prompt=request.prompt)

    monkeypatch.setattr(cli, "_provider_from_chat_args", lambda args, capture_path: FakeProvider())

    assert main(["image", "--prompt", "a cat", "--enhance"]) == 0
    captured = capsys.readouterr()
    assert "file path" in captured.err


def test_provider_errors_are_compact(monkeypatch, capsys):
    async def fail(_args):
        raise ProviderError("first line\n" + ("x" * 2000))

    parser = cli.build_parser()
    monkeypatch.setattr(parser, "parse_args", lambda _argv: argparse.Namespace(func=fail))
    monkeypatch.setattr(cli, "build_parser", lambda **_kwargs: parser)

    assert main(["ignored"]) == 2
    error = capsys.readouterr().err
    assert "\n" not in error.rstrip("\n")
    assert error.startswith("provider error: first line ")
    assert len(error) <= 620


def test_api_edit_saves_locally_without_sending_host_output_path(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        return {
            "id": "edit_test",
            "model": body["model"],
            "data": [
                {
                    "b64_json": "ZWRpdC1ieXRlcw==",
                    "mime_type": "image/png",
                    "path": "/data/outputs/edited.png",
                }
            ],
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    output_path = tmp_path / "edited-local.png"

    exit_code = main(
        [
            "api",
            "edit",
            "--prompt",
            "edit image",
            "--input-image",
            str(source),
            "--output-path",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert calls["method"] == "POST"
    assert calls["path"] == "/images/edits"
    assert "output_dir" not in calls["body"]
    assert "output_path" not in calls["body"]
    assert calls["body"]["input_images"][0]["data_url"].startswith("data:image/png;base64,")
    assert output_path.read_bytes() == b"edit-bytes"


def test_api_research_generates_cancelable_operation_id(monkeypatch, capsys):
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        return {
            "id": "chatcmpl_research",
            "model": body["model"],
            "chatgpt_account": "pro",
            "chatgpt_operation_id": body["chatgpt_operation_id"],
            "chatgpt_research_report_path": "/tmp/report.md",
            "chatgpt_research_report_download_url": "http://127.0.0.1:8000/v1/chatgpt/files/file/report.md",
            "choices": [{"message": {"content": "Deep Research complete."}}],
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    exit_code = main(
        [
            "api",
            "research",
            "--prompt",
            "research this",
            "--operation-id",
            "chatgptop_test",
            "--accounts",
            "free,pro",
            "--account-strategy",
            "failover",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["method"] == "POST"
    assert calls["path"] == "/chat/completions"
    assert calls["body"]["deep_research"] is True
    assert calls["body"]["chatgpt_operation_id"] == "chatgptop_test"
    assert calls["body"]["chatgpt_accounts"] == ["free", "pro"]
    assert calls["body"]["chatgpt_account_strategy"] == "failover"
    assert "api operation --operation-id chatgptop_test" in output
    assert "api cancel --operation-id chatgptop_test" in output
    assert "deep_research_ready=yes" in output


def test_api_research_prints_cancelled_without_provider_error(monkeypatch, capsys):
    async def fake_api_request_json(args, method, path, body):
        raise cli.ProviderError("API POST /chat/completions failed: HTTP 499: ChatGPT Deep Research cancelled")

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    exit_code = main(
        [
            "api",
            "research",
            "--prompt",
            "research this",
            "--operation-id",
            "chatgptop_cancelled",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 130
    assert "Research Cancelled" in captured.out
    assert "operation_id=chatgptop_cancelled" in captured.out
    assert "status=cancelled" in captured.out
    assert "provider error" not in captured.err


def test_api_operation_gets_operation_id(monkeypatch, capsys):
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        return {
            "object": "chatgpt.operation",
            "operation": {
                "id": "chatgptop_test",
                "kind": "research",
                "account": "pro",
                "provider_selected": True,
                "conversation_id": "conversation-1",
                "deep_research_message_id": "message-1",
                "deep_research_session_id": "session-1",
                "deep_research_ready": True,
                "cancel_requested": False,
                "completed": False,
            },
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    exit_code = main(["api", "operation", "--operation-id", "chatgptop_test"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["method"] == "GET"
    assert calls["path"] == "/chatgpt/operations/chatgptop_test"
    assert calls["body"] is None
    assert "Operation Status" in output
    assert "deep_research_ready=yes" in output
    assert "deep_research_session_id=session-1" in output


def test_api_cancel_posts_operation_id(monkeypatch, capsys):
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        return {
            "status": "ok",
            "operation": {
                "id": "chatgptop_test",
                "kind": "research",
                "cancel_requested": True,
                "completed": False,
            },
        }

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    exit_code = main(["api", "cancel", "--operation-id", "chatgptop_test"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["method"] == "POST"
    assert calls["path"] == "/chatgpt/operations/chatgptop_test/cancel"
    assert calls["body"] == {}
    assert "cancel_requested=yes" in output


def test_api_vision_sends_data_url_input_image(tmp_path, monkeypatch):
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    calls = {}

    async def fake_api_request_json(args, method, path, body):
        calls["method"] = method
        calls["path"] = path
        calls["body"] = body
        return {"text": "seen", "mode": "describe", "choices": [{"message": {"content": "seen"}}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    exit_code = main(["api", "vision", "--mode", "describe", "--input-image", str(image_path)])

    assert exit_code == 0
    assert calls["path"] == "/chatgpt/vision"
    assert calls["body"]["input_images"][0]["name"] == "sample.png"
    assert calls["body"]["input_images"][0]["data_url"].startswith("data:image/png;base64,")


def test_account_info_from_account_profile(tmp_path, capsys):
    capture_path = tmp_path / "pro" / "chatgpt-request.txt"
    capture_path.parent.mkdir()
    capture_path.write_text(
        """
URL: https://chatgpt.com/backend-api/f/conversation
Authorization: Bearer header.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsib3BlbmFpX3BsYW5fdHlwZSI6InBybyIsImNoYXRncHRfcGxhbl90eXBlIjoicHJvIn0sImh0dHBzOi8vYXBpLm9wZW5haS5jb20vcHJvZmlsZSI6eyJlbWFpbCI6InByb0BleGFtcGxlLmNvbSJ9fQ.sig
Cookie: oai-last-model-config=%7B%22model%22%3A%22gpt-5-5-thinking%22%2C%22effort%22%3A%22extended%22%7D
Request Data: {"action":"next","model":"gpt-5-5-thinking","thinking_effort":"extended"}
""",
        encoding="utf-8",
    )
    (tmp_path / "pro" / "settings.json").write_text(
        """
{
  "settings": {
    "last_used_model_config": {
      "juices": {"web": {"gpt-5-5-thinking": "max"}},
      "slugs": {"web": "gpt-5-5"}
    },
    "wingman_thinking_effort": "instant"
  },
  "available_options": {"backend_reasoning_effort": ["instant", "medium", "high"]}
}
""",
        encoding="utf-8",
    )

    exit_code = main(["account-info", "--account", "pro", "--accounts-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "plan=pro" in output
    assert "observed_models=gpt-5-5-thinking" in output
    assert "observed_efforts=extended, max, instant, medium, high" in output
    assert "settings_available_reasoning_efforts=instant, medium, high" in output
    assert "pro@example.com" not in output


def test_secrets_rotate_switches_key_file_to_passphrase(tmp_path, capsys, monkeypatch):
    accounts_dir = tmp_path / "accounts"
    account_dir = accounts_dir / "pro"
    account_dir.mkdir(parents=True)
    capture_path = account_dir / "chatgpt-request.txt"

    old_key = load_secrets_key(accounts_dir)
    capture_path.write_text(encrypt_text("URL: https://chatgpt.com\n", old_key), encoding="utf-8")
    assert key_file_path(accounts_dir).exists()

    responses = iter(["new-passphrase", "new-passphrase"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(responses))

    exit_code = main(["secrets", "rotate", "--accounts-dir", str(accounts_dir), "--to-passphrase-prompt"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "pro: rotated" in output
    assert "rotated 1 of 1" in output
    assert not key_file_path(accounts_dir).exists()

    set_runtime_passphrase("new-passphrase")
    new_key = load_secrets_key(accounts_dir)
    clear_runtime_passphrase()
    assert decrypt_text(capture_path.read_text(encoding="utf-8"), new_key) == "URL: https://chatgpt.com\n"


def test_secrets_rotate_encrypts_legacy_plaintext_capture(tmp_path, capsys):
    accounts_dir = tmp_path / "accounts"
    account_dir = accounts_dir / "legacy"
    account_dir.mkdir(parents=True)
    capture_path = account_dir / "chatgpt-request.txt"
    capture_path.write_text("URL: https://chatgpt.com\n", encoding="utf-8")

    exit_code = main(["secrets", "rotate", "--accounts-dir", str(accounts_dir)])

    output = capsys.readouterr().out
    on_disk = capture_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "legacy: encrypted" in output
    assert is_encrypted(on_disk)
    assert decrypt_text(on_disk, load_secrets_key(accounts_dir)) == "URL: https://chatgpt.com\n"


def test_secrets_rotate_to_auto_key_file_ignores_env_passphrase(tmp_path, capsys, monkeypatch):
    accounts_dir = tmp_path / "accounts"
    account_dir = accounts_dir / "pro"
    account_dir.mkdir(parents=True)
    capture_path = account_dir / "chatgpt-request.txt"
    monkeypatch.setenv("CHATGPT_SECRETS_PASSPHRASE", "old-passphrase")
    old_key = load_secrets_key(accounts_dir)
    capture_path.write_text(encrypt_text("URL: https://chatgpt.com\n", old_key), encoding="utf-8")

    exit_code = main(["secrets", "rotate", "--accounts-dir", str(accounts_dir)])

    output = capsys.readouterr().out
    new_key = load_auto_secrets_key(accounts_dir)
    assert exit_code == 0
    assert "pro: rotated" in output
    assert key_file_path(accounts_dir).exists()
    assert decrypt_text(capture_path.read_text(encoding="utf-8"), new_key) == "URL: https://chatgpt.com\n"


def test_secrets_rotate_rejects_mismatched_new_passphrase(tmp_path, capsys, monkeypatch):
    accounts_dir = tmp_path / "accounts"
    account_dir = accounts_dir / "pro"
    account_dir.mkdir(parents=True)
    capture_path = account_dir / "chatgpt-request.txt"
    old_key = load_secrets_key(accounts_dir)
    capture_path.write_text(encrypt_text("URL: https://chatgpt.com\n", old_key), encoding="utf-8")

    responses = iter(["one", "two"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(responses))

    exit_code = main(["secrets", "rotate", "--accounts-dir", str(accounts_dir), "--to-passphrase-prompt"])

    assert exit_code == 2
    assert "did not match" in capsys.readouterr().err
    assert key_file_path(accounts_dir).exists()


def test_account_capabilities_from_account_profile(tmp_path, capsys):
    capture_path = tmp_path / "pro" / "chatgpt-request.txt"
    capture_path.parent.mkdir()
    capture_path.write_text(
        """
URL: https://chatgpt.com/backend-api/f/conversation
Authorization: Bearer header.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsib3BlbmFpX3BsYW5fdHlwZSI6InBybyIsImNoYXRncHRfcGxhbl90eXBlIjoicHJvIn19.sig
Request Data: {"action":"next","model":"gpt-5-5"}
""",
        encoding="utf-8",
    )
    (tmp_path / "pro" / "settings.json").write_text(
        """
{
  "settings": {
    "last_used_model_config": {
      "juices": {"web": {"gpt-5-5-pro": "extended", "gpt-5-5-thinking": "max"}},
      "slugs": {"web": "gpt-5-5"}
    }
  },
  "available_options": {"backend_reasoning_effort": ["instant", "medium", "high"]}
}
""",
        encoding="utf-8",
    )

    exit_code = main(["account-capabilities", "--account", "pro", "--accounts-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "plan=pro" in output
    assert "supported_models=gpt-5-5, gpt-5-5-thinking, gpt-5-5-pro" in output
    assert "default_model=gpt-5-5" in output
    assert "thinking_model=gpt-5-5-thinking" in output
    assert "thinking_efforts=standard, extended, max" in output
    assert "pro_model=gpt-5-5-pro" in output
    assert "pro_efforts=standard, extended" in output
    assert "backend_reasoning_efforts=instant, medium, high" in output
    assert "extra_observed_models=-" in output
