import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from chatgpt_api.extension_bridge import ExtensionQueue, compact_status

CLIENT = "123e4567-e89b-12d3-a456-426614174000"


def beat(q, error=""):
    return q.heartbeat(CLIENT, "test", tab_id=7, input_protocol=4,
                       content_receiver="available", tab_ready=not error, tab_error=error)


@pytest.mark.parametrize("error,reason,action", [
    ("Remove existing attachments before using the image worker", "existing_attachments", "preserve_paired_attachments"),
    ("ChatGPT composer unavailable. Nothing was submitted.", "composer_unavailable", "inspect_paired_composer"),
])
def test_duplicate_and_fifo_survive_blocked_receiver(tmp_path, error, reason, action):
    q = ExtensionQueue(tmp_path, "test")
    beat(q, error)
    one = q.enqueue("first", "image one")["job_id"]
    two = q.enqueue("second", "image two")["job_id"]
    assert q.enqueue("first", "image one")["job_id"] == one
    for _ in range(2):
        assert q.claim(CLIENT) == {}
    assert q._next_action() == action
    for view in (compact_status(q.status(one)), q.wait_for_job(one, 1)):
        assert (view["state"], view["wait_reason"], view["next_action"]) == ("queued", reason, action)
        assert "claimed_at" not in q.jobs[one] and not q.jobs[one].get("delivered")
    q = ExtensionQueue(tmp_path, "test")
    beat(q)
    assert q.claim(CLIENT)["job_id"] == one
    assert q.claim(CLIENT) == {}
    q.result(CLIENT, one, error="test finished before Send")
    assert q.claim(CLIENT)["job_id"] == two


def test_recovery_not_held_by_foreign_attachment(tmp_path):
    q = ExtensionQueue(tmp_path, "test")
    beat(q, "Remove existing attachments before using the image worker")
    jid = q.submit("check uploads", "Create image", preflight_only=True)["job_id"]
    q.jobs[jid]["preflight_cleanup_only"] = True
    q.jobs[jid]["images"] = [{"name": "owned-preflight.png"}]
    assert q.status()["next_action"] == "wait"
    assert q.status(jid)["next_action"] == "wait"
    assert q.claim(CLIENT)["job_id"] == jid


def test_timings_use_observed_stages_only(tmp_path):
    q = ExtensionQueue(tmp_path, "test")
    beat(q)
    jid = q.enqueue("one", "image one")["job_id"]
    assert compact_status(q.status(jid))["queue_wait_ms"] >= 0
    assert "stage_ms" not in compact_status(q.status(jid))
    q.claim(CLIENT)
    q.jobs[jid].update(created_at=1, claimed_at=1.25, remote_started_at=4, result_captured_at=7)
    view = compact_status(q.status(jid))
    assert view["stage_ms"] == {"queue": 250, "generation": 3000}
    assert "queue_wait_ms" not in view


def test_wait_returns_actionable_hold_without_sleeping(tmp_path, monkeypatch):
    q = ExtensionQueue(tmp_path, "test")
    beat(q, "Remove existing attachments before using the image worker")
    jid = q.enqueue("customer-order", "poster")['job_id']
    monkeypatch.setattr(q.finished, "wait", lambda *args: pytest.fail("slept on a known hold"))
    receipt = q.wait_for_job(jid)
    assert receipt['wait_timed_out'] is False
    assert receipt['agent_action'] == 'report_to_user_and_stop'
    assert 'generation_baseline_seconds' not in receipt
    assert 'attachment' in receipt['user_message'] and 'Do not remove' in receipt['user_message']
    assert compact_status(q.status(jid))['user_message'] == receipt['user_message']
    beat(q)
    assert 'user_message' not in compact_status(q.status(jid))
    assert q.claim(CLIENT)['job_id'] == jid


def test_new_blocker_wakes_existing_waiter(tmp_path, monkeypatch):
    q = ExtensionQueue(tmp_path, "test")
    beat(q)
    jid = q.enqueue('wake', 'poster')['job_id']
    entered = Event()
    old_wait = q.finished.wait
    def observe(seconds):
        entered.set()
        return old_wait(seconds)
    monkeypatch.setattr(q.finished, 'wait', observe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiter = pool.submit(q.wait_for_job, jid, 3)
        assert entered.wait(2)
        beat(q, 'ChatGPT composer unavailable. Nothing was submitted.')
        assert waiter.result(timeout=1)['next_action'] == 'inspect_paired_composer'


def test_restart_after_submit_attempt_has_scoped_user_guidance(tmp_path):
    q = ExtensionQueue(tmp_path, 'test')
    beat(q)
    jid = q.enqueue('lost', 'poster')['job_id']
    q.claim(CLIENT)
    q.phase(CLIENT, jid, 'submit_attempted', 7)
    q = ExtensionQueue(tmp_path, 'test')
    receipt = compact_status(q.status(jid))
    assert receipt['state'] == 'interrupted' and receipt['next_action'] == 'inspect_halted_job'
    assert receipt['agent_action'] == 'report_to_user_and_stop'
    assert receipt['remote_delivery'] == 'unknown' and receipt['safe_to_retry'] is False
    assert 'แม้แชตว่าง' in receipt['user_message_th']
    assert 'Do not resubmit' in receipt['user_message'] and not receipt['image_path']
