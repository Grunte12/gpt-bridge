"""Offline regression tests for image thinking-effort forwarding."""

import json
from pathlib import Path

import pytest

import chatgpt_api.api.openai_compat as compat
import chatgpt_api.cli as cli
from chatgpt_api.api.openai_compat import OpenAICompatConfig, _image_edit, _image_generation
from chatgpt_api.core.types import ImageAsset, ImageRequest, ImageResponse
from chatgpt_api.providers.chatgpt.auth import ChatGPTAuthConfig
from chatgpt_api.providers.chatgpt.transport import ChatGPTEndpoints, ChatGPTWebTransport


@pytest.mark.parametrize(
    ("operation", "requested_model", "resolved_model"),
    [
        ("generate", "gpt-6-thinking", "gpt-6-thinking"),
        ("edit", "gpt-6-thinking", "gpt-6-thinking"),
        ("edit", "gpt-5-6-sol-high", "gpt-5-6-thinking"),
    ],
)
def test_image_api_passes_resolved_model_and_effort(
    monkeypatch, tmp_path, operation, requested_model, resolved_model
):
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"png")
    captured = []

    async def fake_generate(_config, _router, request, *_args, **_kwargs):
        captured.append(request)
        return "pro", ImageResponse(images=[ImageAsset(data=b"png", mime_type="image/png")], prompt=request.prompt)

    monkeypatch.setattr(compat, "_generate_image_with_accounts", fake_generate)
    config = OpenAICompatConfig(account="pro", accounts=("pro",), image_output_dir=tmp_path)
    body = {
        "model": requested_model,
        "thinking_effort": "extended",
        "prompt": "a small icon",
        "response_format": "b64_json",
    }
    if operation == "edit":
        body["images"] = [str(image_path)]

    handler = _image_generation if operation == "generate" else _image_edit
    compat.asyncio.run(handler(config, body))

    assert len(captured) == 1
    assert captured[0].model == resolved_model
    assert captured[0].thinking_effort == "extended"


def test_transport_image_payload_includes_thinking_effort():
    transport = ChatGPTWebTransport(ChatGPTAuthConfig(access_token="fake"), refresh_web_tokens=False)
    payload = transport._build_image_chat_payload(
        ImageRequest(prompt="draw a cat", model="gpt-6-thinking", thinking_effort="extended"),
        [],
    )
    assert payload["model"] == "gpt-6-thinking"
    assert payload["thinking_effort"] == "extended"


def test_operation_hook_clone_preserves_model_and_thinking_effort():
    original = ImageRequest(
        prompt="draw a cat", model="gpt-6-thinking", thinking_effort="extended"
    )
    hooked = compat._image_request_with_operation_hooks(original, "operation-1")
    assert hooked.model == "gpt-6-thinking"
    assert hooked.thinking_effort == "extended"


@pytest.mark.parametrize(
    "argv",
    [
        ["worker", "--transport", "http", "image", "--prompt", "cat", "--thinking-effort", "extended", "--brief"],
        ["worker", "--transport", "http", "edit", "--prompt", "edit", "--input-image", "{image}", "--thinking-effort", "extended", "--brief"],
        ["api", "image", "--prompt", "cat", "--thinking-effort", "extended", "--json"],
        ["api", "edit", "--prompt", "edit", "--input-image", "{image}", "--thinking-effort", "extended", "--json"],
    ],
)
def test_cli_image_generate_and_edit_forward_thinking_effort(tmp_path, monkeypatch, capsys, argv):
    source = tmp_path / "source.png"
    source.write_bytes(b"png")
    argv = [str(source) if item == "{image}" else item for item in argv]
    calls = []

    async def fake_api_request_json(_args, method, path, body):
        calls.append((method, path, body))
        return {"data": [{"url": "https://example.test/image.png"}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    assert cli.main(argv) == 0
    capsys.readouterr()
    assert calls
    assert calls[0][0] == "POST"
    assert calls[0][2]["thinking_effort"] == "extended"


def test_counted_image_session_retry_preserves_thinking_effort(tmp_path, monkeypatch, capsys):
    calls = []

    async def fake_api_request_json(_args, _method, _path, body):
        calls.append(body)
        if len(calls) == 1:
            return {
                "chatgpt_conversation_id": "conversation-1",
                "chatgpt_message_id": "message-1",
                "data": [{"url": "https://example.test/one.png"}],
            }
        if len(calls) == 2:
            raise cli.ProviderError("continuation failed")
        return {"data": [{"url": "https://example.test/retry.png"}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    assert cli.main(
        [
            "worker", "--transport", "http", "image", "--prompt", "cat",
            "--count", "2", "--thinking-effort", "extended", "--brief",
        ]
    ) == 0
    capsys.readouterr()
    assert len(calls) == 3
    assert [body["thinking_effort"] for body in calls] == ["extended"] * 3


def _install_direct_doctor_client(monkeypatch):
    class FakeClient:
        account = "pro"

        async def request_json(self, _method, path, body=None):
            if path == "/chatgpt/usage":
                return {"accounts": []}
            if path == "/models":
                return {"data": [{"id": "gpt-5-6-thinking"}]}
            return {"ok": True}

    monkeypatch.setattr(cli, "_worker_client", lambda _args: FakeClient())
    monkeypatch.setattr(cli, "resolve_account_capture_path", lambda *_args: Path("capture.json"))
    monkeypatch.setattr(cli.CapturedRequest, "from_file", lambda _path: object())


def test_worker_doctor_live_models_uses_fresh_picker_without_changing_default(monkeypatch, capsys):
    _install_direct_doctor_client(monkeypatch)
    monkeypatch.setattr(
        cli, "_fetch_account_models",
        lambda _capture, _browser: {
            "default_model_slug": "gpt-6-thinking",
            "models": ["gpt-6-thinking"],
            "versions": [],
        },
    )

    assert cli.main(["worker", "--transport", "direct", "doctor", "--live-models", "--json"]) == 0
    live = json.loads(capsys.readouterr().out)["checks"]["models"]
    assert live["source"] == "live_account_picker"
    assert live["data"]["default_model_slug"] == "gpt-6-thinking"

    assert cli.main(["worker", "--transport", "direct", "doctor", "--json"]) == 0
    captured = json.loads(capsys.readouterr().out)["checks"]["models"]
    assert captured["source"] == "capture_inference"


def test_worker_doctor_live_models_failure_does_not_fall_back_to_capture(monkeypatch, capsys):
    _install_direct_doctor_client(monkeypatch)

    def fail_fresh_models(_capture, _browser):
        raise cli.ProviderError("fresh picker unavailable")

    monkeypatch.setattr(cli, "_fetch_account_models", fail_fresh_models)
    assert cli.main(["worker", "--transport", "direct", "doctor", "--live-models", "--json"]) == 1
    models = json.loads(capsys.readouterr().out)["checks"]["models"]
    assert models == {
        "ok": False,
        "source": "live_account_picker",
        "detail": "fresh picker unavailable",
    }


def test_worker_doctor_live_models_is_direct_only(monkeypatch, capsys):
    assert cli.main(["worker", "--transport", "http", "doctor", "--live-models", "--json"]) == 2
    assert "requires the direct worker transport" in capsys.readouterr().err
