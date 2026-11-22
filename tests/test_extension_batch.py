import hashlib
import json
import time
from pathlib import Path

import pytest
from chatgpt_api.extension_bridge import ExtensionQueue

CLIENT = "123e4567-e89b-12d3-a456-426614174000"


def item(sid):
    prompt = "prompt " + sid
    return {"scenario_id": sid, "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}


@pytest.fixture
def setup(tmp_path):
    dest, marks = tmp_path / "raw", tmp_path / "receipts"
    dest.mkdir(); marks.mkdir()
    (tmp_path / "prompts.json").write_text(json.dumps([item(x) for x in ["a", "b", "old", "z", "different"]]))
    (tmp_path / "generation_log.tsv").write_text("scenario_id\tstatus\n")
    q = ExtensionQueue(tmp_path / "queue", "test", batch_allowed_runs=[tmp_path])
    q.pair(CLIENT, "test", "Create image", input_protocol=3, tab_id=7)
    q.heartbeat(CLIENT, "test", tab_ready=True, tab_id=7)
    return q, dest, marks


def start(q, dest, marks, items=None):
    return q.batch_start("batch1", items or [item("a"), item("b")], str(dest), str(marks))


def test_manifest_idempotency_and_attempt_collision(setup):
    q, dest, marks = setup
    (marks / "old-attempt.json").write_text("{}")
    with pytest.raises(ValueError, match="already attempted"):
        start(q, dest, marks, [item("old")])
    first = start(q, dest, marks)
    assert start(q, dest, marks)["manifest_hash"] == first["manifest_hash"]
    with pytest.raises(ValueError, match="different manifest"):
        start(q, dest, marks, [item("different")])
    with pytest.raises(ValueError, match="duplicate"):
        start(q, dest, marks, [item("z"), item("z")])


def test_one_job_marker_before_queue_and_fail_stops(setup):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    entry = record["progress"][0]
    assert entry["state"] == "reserved"
    assert json.loads((marks / "a-attempt.json").read_text())["job_id"] == entry["job_id"]
    assert len(q.jobs) == 1
    claimed = q.claim(CLIENT)
    q.result(CLIENT, claimed["job_id"], error="CAPTCHA")
    q._batch.tick(record)
    assert record["state"] == "stopped"
    assert record["progress"][1]["state"] == "untouched"
    assert len(q.jobs) == 1


def test_restart_never_replays_reserved_job(setup):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    jid = record["progress"][0]["job_id"]
    q2 = ExtensionQueue(q.root, "test")
    assert q2.batch_status("batch1")["state"] == "stopped"
    assert set(q2.jobs) == {jid}
    assert q2.jobs[jid]["state"] == "interrupted"


def test_timeout_never_deletes_or_replaces(setup):
    q, dest, marks = setup
    start(q, dest, marks)
    q._batch.tick(q._batch.batches["batch1"])
    job = q.claim(CLIENT)
    jid = job["job_id"]
    q.phase(CLIENT, jid, "submit_attempted", 7)
    q.phase(CLIENT, jid, "remote_started", 7, "/c/123e4567-e89b-12d3-a456-426614174000")
    q.jobs[jid]["remote_started_at"] = time.time() - 2000
    with pytest.raises(ValueError, match="No deletion"):
        q.timeout(CLIENT, jid, "/c/123e4567-e89b-12d3-a456-426614174000")
    assert q.jobs[jid].get("cleanup_status") != "timeout_delete_pending"
    assert q.halted_job == jid
    assert len(q.jobs) == 1


def test_saved_image_copied_and_next_refilled(setup):
    import base64
    import io
    from PIL import Image
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    job = q.claim(CLIENT)
    jid = job["job_id"]
    path = "/c/123e4567-e89b-12d3-a456-426614174000"
    q.phase(CLIENT, jid, "submit_attempted", 7)
    q.phase(CLIENT, jid, "remote_started", 7, path)
    q.phase(CLIENT, jid, "result_captured", 7, path)
    img = Image.new("RGB", (512, 512), "blue")
    buf = io.BytesIO(); img.save(buf, format="PNG")
    q.result(CLIENT, jid, image_base64=base64.b64encode(buf.getvalue()).decode(), chat_path=path)
    q._batch.tick(record)
    assert record["progress"][0]["state"] == "saved"
    assert hashlib.sha256((dest / "a.png").read_bytes()).hexdigest() == record["progress"][0]["sha256"]
    assert record["progress"][1]["state"] == "reserved"
    assert len(q.jobs) == 2


def test_stopped_batch_cannot_deliver_already_queued_job(setup):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    q._batch._stop(record, "CAPTCHA")
    batch_id = record["progress"][0]["job_id"]
    ordinary = q.submit("ordinary prompt", "Create image")
    assert q.claim(CLIENT)["job_id"] == ordinary["job_id"]
    assert q.jobs[batch_id]["state"] == "interrupted"
    assert q.jobs[batch_id].get("delivered") is not True


def test_stopped_ambiguous_batch_job_is_not_canceled_or_replayed(setup):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    jid = record["progress"][0]["job_id"]
    q.jobs[jid]["delivered"] = True
    q._batch._stop(record, "uncertain delivery")
    q.submit("ordinary prompt", "Create image")
    assert q.claim(CLIENT) == {}
    assert q.jobs[jid]["state"] == "queued"
    assert q.jobs[jid]["delivered"] is True


def test_reservation_without_job_is_uncertain_and_never_replayed(setup, monkeypatch):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    def fail(*args, **kwargs):
        raise OSError("synthetic crash before queue receipt")
    monkeypatch.setattr(q, "submit", fail)
    with pytest.raises(OSError):
        q._batch.tick(record)
    assert (marks / "a-attempt.json").exists()
    q._batch.tick(record)
    assert record["state"] == "stopped"
    assert record["progress"][1]["state"] == "untouched"
    assert not q.jobs


def test_default_deny_and_alternate_attempt_directory_rejected(setup, tmp_path):
    q, dest, marks = setup
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="not explicitly allowed"):
        start(q, dest, other)
    q.batch_allowed_runs = frozenset()
    with pytest.raises(ValueError, match="not explicitly allowed"):
        start(q, dest, marks)


def test_changed_prompt_and_ledger_attempt_are_rejected(setup):
    q, dest, marks = setup
    with pytest.raises(ValueError, match="prompt registry"):
        start(q, dest, marks, [dict(item("a"), prompt="changed", prompt_sha256=hashlib.sha256(b"changed").hexdigest())])
    (dest.parent / "generation_log.tsv").write_text("scenario_id\tstatus\na\tuncertain\n")
    with pytest.raises(ValueError, match="already attempted"):
        start(q, dest, marks, [item("a")])


def test_exact_82_excludes_18_attempts(tmp_path):
    dest = tmp_path / "raw"; marks = tmp_path / "receipts"
    dest.mkdir(); marks.mkdir()
    all_items = [item("id%03d" % i) for i in range(100)]
    (tmp_path / "prompts.json").write_text(json.dumps(all_items))
    (tmp_path / "generation_log.tsv").write_text("scenario_id\tstatus\n" + "".join("id%03d\tuncertain\n" % i for i in range(18)))
    for i in range(18):
        (marks / ("id%03d-attempt.json" % i)).write_text("{}")
    q = ExtensionQueue(tmp_path / "queue", "test", batch_allowed_runs=[tmp_path])
    q.pair(CLIENT, "test", "Create image", input_protocol=3, tab_id=7)
    q.heartbeat(CLIENT, "test", tab_ready=True, tab_id=7)
    with pytest.raises(ValueError, match="already attempted"):
        q.batch_start("bad", all_items, str(dest), str(marks))
    result = q.batch_start("good", all_items[18:], str(dest), str(marks))
    assert len(result["progress"]) == 82
    assert {x["scenario_id"] for x in result["progress"]}.isdisjoint({"id%03d" % i for i in range(18)})


def test_job_image_must_be_contained_regular_nonsymlink(setup, tmp_path):
    from chatgpt_api.extension_batch import validated_job_image
    q, _, _ = setup
    jobid = "a" * 32
    directory = q.root / jobid; directory.mkdir()
    outside = tmp_path / "outside.png"; outside.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="outside"):
        validated_job_image(q, {"job_id": jobid, "image_path": str(outside)})
    link = directory / "image.png"; link.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        validated_job_image(q, {"job_id": jobid, "image_path": str(link)})
    link.unlink(); link.write_bytes(b"ok")
    assert validated_job_image(q, {"job_id": jobid, "image_path": str(link)})[1] == b"ok"


def test_symlinked_run_paths_rejected(setup, tmp_path):
    q, dest, marks = setup
    link = tmp_path / "linked"
    link.symlink_to(dest, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        start(q, link, marks)
    registry = dest.parent / "prompts.json"
    registry.rename(dest.parent / "real-prompts.json")
    registry.symlink_to(dest.parent / "real-prompts.json")
    with pytest.raises((ValueError, OSError)):
        start(q, dest, marks)


def test_busy_tab_waits_for_current_job_then_copies_before_next_submit(setup):
    import base64
    import io
    from PIL import Image
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    jid = q.claim(CLIENT)["job_id"]
    chat = "/c/123e4567-e89b-12d3-a456-426614174000"
    q.phase(CLIENT, jid, "submit_attempted", 7)
    q.phase(CLIENT, jid, "remote_started", 7, chat)
    q.heartbeat(CLIENT, "test", tab_ready=False, tab_id=7)
    q._batch.tick(record)
    assert record["state"] == "running"
    assert len(q.jobs) == 1 and record["progress"][1]["state"] == "untouched"
    q.phase(CLIENT, jid, "result_captured", 7, chat)
    buf = io.BytesIO(); Image.new("RGB", (512, 512), "blue").save(buf, format="PNG")
    q.result(CLIENT, jid, image_base64=base64.b64encode(buf.getvalue()).decode(), chat_path=chat)
    q._batch.tick(record)
    assert record["progress"][0]["state"] == "saved"
    assert record["progress"][1]["state"] == "untouched"
    q.heartbeat(CLIENT, "test", tab_ready=True, tab_id=7)
    q._batch.tick(record)
    assert record["progress"][1]["state"] == "reserved"
    assert len(q.jobs) == 2


def test_offline_during_claim_stops_batch(setup):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    jid = q.claim(CLIENT)["job_id"]
    q.client["seen"] = time.monotonic() - 100
    q._batch.tick(record)
    assert record["state"] == "stopped"
    assert record["progress"][0]["job_id"] == jid
    assert record["progress"][1]["state"] == "untouched"


def test_content_worker_running_heartbeat_is_benign_only_during_owned_remote_job(setup):
    import base64
    import io
    from PIL import Image
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    jid = q.claim(CLIENT)["job_id"]
    chat = "/c/123e4567-e89b-12d3-a456-426614174000"
    q.phase(CLIENT, jid, "submit_attempted", 7)
    q.phase(CLIENT, jid, "remote_started", 7, chat)
    q.heartbeat(CLIENT, "test", tab_ready=False, tab_id=7, tab_error="Content worker already running")
    q._batch.tick(record)
    assert record["state"] == "running" and len(q.jobs) == 1
    q.phase(CLIENT, jid, "result_captured", 7, chat)
    buf = io.BytesIO(); Image.new("RGB", (512, 512), "blue").save(buf, format="PNG")
    q.result(CLIENT, jid, image_base64=base64.b64encode(buf.getvalue()).decode(), chat_path=chat)
    q._batch.tick(record)  # The previous busy heartbeat may outlive the result.
    assert record["progress"][0]["state"] == "saved"
    assert record["progress"][1]["state"] == "untouched" and record["state"] == "running"
    q.heartbeat(CLIENT, "test", tab_ready=True, tab_id=7, tab_error="")
    q._batch.tick(record)
    assert record["progress"][1]["state"] == "reserved"


@pytest.mark.parametrize("error,category", [
    ("Owner action required: complete verification", "verification"),
    ("Sign in to continue", "access"), ("HTTP 403", "access"),
    ("HTTP 429", "rate_limit"), ("Account restricted", "restriction"),
    ("Content worker already running plus extra", "other"),
])
def test_active_job_real_errors_stop_with_redacted_diagnostic(setup, error, category):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    jid = q.claim(CLIENT)["job_id"]
    chat = "/c/123e4567-e89b-12d3-a456-426614174000"
    q.phase(CLIENT, jid, "submit_attempted", 7)
    q.phase(CLIENT, jid, "remote_started", 7, chat)
    q.heartbeat(CLIENT, "test", tab_ready=False, tab_id=7, tab_error=error)
    q._batch.tick(record)
    snapshot = q.batch_status("batch1")["stop_detail"]
    assert record["state"] == "stopped" and snapshot["tab_error_class"] == category
    assert snapshot["owned_job_phase"] == "remote_started" and error not in str(snapshot)
    assert record["progress"][1]["state"] == "untouched"


def test_exact_busy_string_waits_without_submitting(setup):
    q, dest, marks = setup
    start(q, dest, marks)
    record = q._batch.batches["batch1"]
    q._batch.tick(record)
    q.claim(CLIENT)
    q.heartbeat(CLIENT, "test", tab_ready=False, tab_id=7, tab_error="Content worker already running")
    q._batch.tick(record)
    assert record["state"] == "running" and len(q.jobs) == 1


def test_auto_cleanup_waits_for_hash_verified_batch_copy_and_cleanup_before_next(setup):
    import base64
    import io
    from PIL import Image
    q, dest, marks = setup
    q.auto_delete_saved_chats = True
    start(q, dest, marks)
    record = q._batch.batches['batch1']
    q._batch.tick(record)
    job = q.claim(CLIENT)
    assert job['auto_delete_saved_chat'] is True
    jid = job['job_id']; chat = '/c/123e4567-e89b-12d3-a456-426614174000'
    for phase in ('submit_attempted', 'remote_started', 'result_captured'):
        q.phase(CLIENT, jid, phase, 7, '' if phase == 'submit_attempted' else chat)
    buf = io.BytesIO(); Image.new('RGB', (512, 512), 'blue').save(buf, format='PNG')
    saved = q.result(CLIENT, jid, image_base64=base64.b64encode(buf.getvalue()).decode(),
                     cleanup_pending=True, chat_path=chat)
    assert saved['cleanup_status'] == 'pending'
    assert hashlib.sha256((dest / 'a.png').read_bytes()).hexdigest() == saved['sha256']
    assert record['progress'][0]['state'] == 'saved'
    q._batch.tick(record)
    assert record['progress'][1]['state'] == 'untouched'
    q.cleanup(CLIENT, jid, 'confirmation_required')
    assert q.claim_delete_confirmation(CLIENT, jid) == {'confirmed': True}
    q.cleanup(CLIENT, jid, 'deleted')
    q._batch.tick(record)
    assert record['progress'][1]['state'] == 'reserved'


def test_batch_copy_failure_preserves_chat_and_stops(setup, monkeypatch):
    import base64
    import io
    from PIL import Image
    q, dest, marks = setup
    q.auto_delete_saved_chats = True
    start(q, dest, marks); record = q._batch.batches['batch1']; q._batch.tick(record)
    jid = q.claim(CLIENT)['job_id']; chat = '/c/123e4567-e89b-12d3-a456-426614174000'
    for phase in ('submit_attempted', 'remote_started', 'result_captured'):
        q.phase(CLIENT, jid, phase, 7, '' if phase == 'submit_attempted' else chat)
    def failed_copy(*args): raise OSError('synthetic copy failure')
    monkeypatch.setattr(q._batch, 'save_result', failed_copy)
    buf = io.BytesIO(); Image.new('RGB', (512, 512), 'blue').save(buf, format='PNG')
    saved = q.result(CLIENT, jid, image_base64=base64.b64encode(buf.getvalue()).decode(),
                     cleanup_pending=True, chat_path=chat)
    assert saved['cleanup_status'] == 'failed' and record['state'] == 'stopped'
    assert record['progress'][1]['state'] == 'untouched'
    assert Path(saved['image_path']).is_file()


def test_auto_cleanup_rejects_unbound_chat_before_any_output_or_delete(tmp_path):
    q = ExtensionQueue(tmp_path / 'queue', 'test', auto_delete_saved_chats=True)
    q.pair(CLIENT, 'test', 'Create image')
    job = q.submit('synthetic prompt', 'Create image')
    q.claim(CLIENT)
    with pytest.raises(ValueError, match='exact bound job'):
        q.result(CLIENT, job['job_id'], image_base64='ignored', cleanup_pending=True,
                 chat_path='/c/123e4567-e89b-12d3-a456-426614174000')
    assert q.jobs[job['job_id']]['state'] == 'claimed'
    assert not (q.root / job['job_id'] / 'image.png').exists()
