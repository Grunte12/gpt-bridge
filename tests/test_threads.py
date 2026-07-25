import json

import pytest

import chatgpt_api.cli as cli
from chatgpt_api.cli import main
from chatgpt_api.threads import ThreadState, load_thread, lock_thread, save_thread


def test_api_chat_thread_appends_context_across_worker_calls(tmp_path, monkeypatch, capsys):
    calls = []

    async def fake_api_request_json(args, method, path, body):
        calls.append(body)
        return {"choices": [{"message": {"content": f"reply {len(calls)}"}}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)
    common = ["api", "chat", "--thread", "research", "--threads-dir", str(tmp_path), "--json"]

    assert main([*common, "--message", "first"]) == 0
    assert main([*common, "--message", "second"]) == 0

    state = load_thread(tmp_path, "research")
    assert state.messages == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply 1"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "reply 2"},
    ]
    assert calls[1]["messages"] == state.messages[:-1]
    assert '"chatgpt_thread": "research"' in capsys.readouterr().out


def test_api_chat_thread_compacts_old_context_before_worker_call(tmp_path, monkeypatch, capsys):
    save_thread(
        tmp_path,
        ThreadState(
            name="review",
            messages=[
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
                {"role": "assistant", "content": "a2"},
                {"role": "user", "content": "u3"},
            ],
        ),
    )
    calls = []

    async def fake_api_request_json(args, method, path, body):
        calls.append(body)
        if body["messages"][0]["content"].startswith("Summarize this prior"):
            return {"choices": [{"message": {"content": "summary"}}]}
        return {"choices": [{"message": {"content": "final answer"}}]}

    monkeypatch.setattr(cli, "_api_request_json", fake_api_request_json)

    assert main(
        [
            "api",
            "chat",
            "--thread",
            "review",
            "--threads-dir",
            str(tmp_path),
            "--thread-window",
            "2",
            "--message",
            "continue",
            "--json",
        ]
    ) == 0

    state = load_thread(tmp_path, "review")
    assert len(calls) == 2
    assert state.compacted_summary == "summary"
    assert state.messages == [
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "final answer"},
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["chatgpt_thread_compacted"] is True


def test_thread_lock_rejects_a_second_writer(tmp_path):
    with lock_thread(tmp_path, "shared"):
        with pytest.raises(ValueError, match="already in use"):
            with lock_thread(tmp_path, "shared"):
                pass
