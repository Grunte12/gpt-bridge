import json

import pytest

from chatgpt_api.extension_bridge import ExtensionQueue, ended_uncertain


def failed_pair(tmp_path):
    q = ExtensionQueue(tmp_path, "test")
    ids = ["a" * 32, "b" * 32]
    with q.lock:
        for jid in ids:
            job = dict(job_id=jid, account="test", state="failed", phase="remote_started",
                       phase_capable=True, delivered=True, error="submitted; uncertain")
            q.jobs[jid] = job
            q._save(job)
    return q, ids


def test_operator_inspection_survives_restart_and_further_halt_selection(tmp_path):
    q, (a, b) = failed_pair(tmp_path)
    q.resolve(a, inspected_chatgpt=True)
    assert q.halted_job == b
    loaded = ExtensionQueue(tmp_path, "test")
    assert {k for k, v in loaded.jobs.items() if ended_uncertain(v)} == {b}
    assert loaded.jobs[a]["state"] == "failed"


def test_disk_failure_cannot_advance_inspected_halt(tmp_path, monkeypatch):
    q, (a, _) = failed_pair(tmp_path)
    def fail_write(job):
        raise OSError("disk full")
    monkeypatch.setattr(q, "_save", fail_write)
    with pytest.raises(OSError):
        q.resolve(a, inspected_chatgpt=True)
    assert q.halted_job == a and ended_uncertain(q.jobs[a])
    assert ended_uncertain(json.loads((tmp_path / a / "state.json").read_text()))
