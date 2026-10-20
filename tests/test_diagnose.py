"""Offline tests for the read-only scripts/diagnose.py findings."""

import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("diagnose", Path(__file__).resolve().parent.parent / "scripts" / "diagnose.py")
diagnose = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnose)

CHAT = "/c/123e4567-e89b-12d3-a456-426614174000"
TOKEN = "synthetic-local-token-with-enough-length"


def _dom(**overrides):
    return {"assistant_role_nodes": 1, "user_headings": 1, "assistant_headings": 1, "assistant_body_found": True,
            "assistant_images": 0, "conversation_images": 0, "busy": False, "chat_path": CHAT, **overrides}


def _status(dom=None, **overrides):
    return {"extension_online": True, "installed_extension_version": "1.0", "tab_error": "",
            "extension_diagnostics": {"worker_version": "1.0", "content_receiver": "available",
                                      "chatgpt_tabs": 0, "result_dom": dom}, **overrides}


def test_healthy_paired_tab_with_zero_tab_count_is_not_a_finding():
    assert diagnose.verdict(_status(_dom()), None) == ["no problem found in the numbers"]


def test_missing_paired_tab_and_offline_and_version_mismatch():
    status = _status(None, extension_online=False, installed_extension_version="1.1")
    status["extension_diagnostics"]["content_receiver"] = "tab_missing"
    notes = diagnose.verdict(status, None)
    assert [note.split(":")[0] for note in notes] == ["extension offline", "paired tab missing and no chatgpt.com tab found",
                                                      "version mismatch"]


def test_running_job_page_states():
    job = {"state": "claimed", "phase": "remote_started"}
    assert "still generating" in diagnose.verdict(_status(_dom(busy=True)), job)[0]
    assert "selector misses" in diagnose.verdict(_status(_dom(conversation_images=2)), job)[0]
    assert "output image and is idle" in diagnose.verdict(_status(_dom(assistant_images=1)), job)[0]


def test_timeout_error_dom_is_read_and_compared_with_the_live_chat():
    error = ("Submission attempted. Timed out; generation may still complete. Inspect ChatGPT before resubmitting. DOM: "
             + json.dumps(_dom(conversation_images=1)))
    job = {"state": "failed", "phase": "remote_started", "chat_path": CHAT, "error": error}
    notes = diagnose.verdict(_status(_dom(assistant_images=1)), job)
    assert notes[0].startswith("at timeout: page has images but none inside the assistant message")
    assert notes[1].startswith("that job's chat shows an output image now")
    # A report cut by the 500-char error limit is ignored, not misread.
    assert diagnose.verdict(_status(_dom()), {**job, "error": error[:-5]}) == ["no problem found in the numbers"]


def test_offline_worker_prints_a_short_error_without_token(monkeypatch, capsys):
    monkeypatch.setattr(diagnose, "read_token", lambda _root: TOKEN)
    def offline(self, action, data, timeout=10):
        raise ValueError("Local extension worker unavailable or request rejected; inspect status before retrying. No automatic retry.")
    monkeypatch.setattr(diagnose.ExtensionClient, "call", offline)
    monkeypatch.setattr("sys.argv", ["diagnose.py"])
    assert diagnose.main() == 1
    out = capsys.readouterr()
    assert "worker unreachable" in out.err and "Traceback" not in out.err
    assert TOKEN not in out.out + out.err


def test_unreadable_token_names_only_the_error_type(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(diagnose, "DATA_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["diagnose.py"])
    assert diagnose.main() == 2
    assert "FileNotFoundError" in capsys.readouterr().err
