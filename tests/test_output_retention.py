"""Retention: the bridge copy is temporary, state.json stays for no-replay, work in progress is never touched."""
from __future__ import annotations

import os
import time

import pytest

from chatgpt_api.extension_bridge import ExtensionQueue, compact_status, main, run_image
from chatgpt_api.retention import prune_old_files, ttl_seconds
from tests.test_run_workflow import CLIENT, Extension, _beat, _finish, _png, _queue, _start

DAY = 86400


@pytest.fixture(autouse=True)
def _no_installed_version(monkeypatch):
    monkeypatch.setattr("chatgpt_api.extension_bridge.repo_extension_version", lambda: None)
    monkeypatch.delenv("GPT_BRIDGE_OUTPUT_TTL_DAYS", raising=False)


def _reference(tmp_path):
    path = tmp_path / "ref.png"
    path.write_bytes(_png(size=(512, 512))[1])
    return [{"path": str(path), "role": "reference", "description": "ref"}]


def _completed(queue, **submit):
    queue.submit("draw a cat", "Create image", **submit)
    claimed = _start(queue)
    _finish(queue, claimed)
    return claimed["job_id"]


def _age(queue, job_id, days):
    """Make a finished job look `days` old: completed_at and state.json mtime."""
    old = time.time() - days * DAY
    queue.jobs[job_id]["completed_at"] = old
    queue._save_keep_mtime(queue.jobs[job_id])
    os.utime(queue.root / job_id / "state.json", (old, old))


def test_ttl_default_env_and_zero():
    assert ttl_seconds() == 7 * DAY
    assert ttl_seconds(0) == 0
    assert ttl_seconds("1.5") == 1.5 * DAY
    with pytest.raises(ValueError):
        ttl_seconds(-1)


def test_ttl_env_override(monkeypatch):
    monkeypatch.setenv("GPT_BRIDGE_OUTPUT_TTL_DAYS", "2")
    assert ttl_seconds() == 2 * DAY


def test_inputs_are_deleted_when_the_job_ends_but_metadata_stays(tmp_path):
    queue = _queue(tmp_path)
    submitted = queue.submit("edit this", "Create image", images=_reference(tmp_path))
    name = submitted["images"][0]["name"]
    pinned = queue.root / submitted["job_id"] / name
    assert pinned.is_file()  # Queued: the one delivery still needs these bytes.
    claimed = _start(queue)
    assert claimed["images"][0]["data_base64"]
    assert pinned.is_file()  # Claimed (in progress): untouched.
    _finish(queue, claimed)
    assert not pinned.exists()
    record = queue.jobs[submitted["job_id"]]
    assert record["images"][0]["name"] == name and record["images"][0]["sha256"]


def test_failed_job_also_drops_inputs(tmp_path):
    queue = _queue(tmp_path)
    submitted = queue.submit("edit this", "Create image", images=_reference(tmp_path))
    claimed = queue.claim(CLIENT)
    queue.result(CLIENT, claimed["job_id"], error="Not submitted. Native uploads not verified ready; x")
    assert not list((queue.root / submitted["job_id"]).glob("input-*"))


def test_fresh_output_is_kept_and_receipt_says_copy_it(tmp_path):
    queue = _queue(tmp_path)
    job_id = _completed(queue)
    receipt = queue.wait_for_job(job_id, 1)
    assert receipt["output_status"] == "available"
    assert receipt["output_expires_at"].endswith("Z")
    assert "Copy it into your project" in receipt["output_note"]
    short = compact_status(queue.status(job_id))
    assert short["output_status"] == "available" and short["output_expires_at"] == receipt["output_expires_at"]
    assert (queue.root / job_id / "image.png").is_file()


def test_old_output_expires_but_state_json_and_hash_stay(tmp_path):
    queue = _queue(tmp_path)
    job_id = _completed(queue)
    digest = queue.jobs[job_id]["sha256"]
    _age(queue, job_id, 8)
    mtime = (queue.root / job_id / "state.json").stat().st_mtime_ns
    assert queue.prune()["outputs_expired"] == 1
    assert not (queue.root / job_id / "image.png").exists()
    assert (queue.root / job_id / "state.json").stat().st_mtime_ns == mtime  # "latest job" order is unchanged.
    short = compact_status(queue.status(job_id))
    assert short["output_status"] == "expired" and short["image_path"] is None
    assert short["sha256"] == digest and short["state"] == "complete"
    assert "never re-run" in short["output_note"]
    assert queue.prune()["outputs_expired"] == 0  # Idempotent.
    reloaded = ExtensionQueue(queue.root, "test")  # Expired status survives restart.
    assert reloaded.status(job_id)["output_status"] == "expired"


def test_zero_ttl_keeps_outputs(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", "test", output_ttl_seconds=0)
    queue.pair(CLIENT, "test", "Create image", input_protocol=4, tab_id=17)
    _beat(queue)
    job_id = _completed(queue)
    _age(queue, job_id, 400)
    assert queue.prune()["outputs_expired"] == 0
    assert (queue.root / job_id / "image.png").is_file()
    assert "output_expires_at" not in queue.wait_for_job(job_id, 1)


def test_prune_never_touches_work_in_progress_or_open_cleanup(tmp_path):
    queue = _queue(tmp_path)
    queue.submit("draw a cat", "Create image")
    claimed = _start(queue)
    queue.jobs[claimed["job_id"]]["created_at"] -= 30 * DAY
    assert queue.prune() == {"outputs_expired": 0, "inputs_removed": 0, "stale_requests_expired": 0}
    assert queue.jobs[claimed["job_id"]]["state"] == "claimed"
    # Finished, but the chat delete is still open: the image stays.
    encoded, _raw = _png()
    queue.phase(CLIENT, claimed["job_id"], "result_captured", 17, "/c/123e4567-e89b-12d3-a456-426614174000")
    queue.result(CLIENT, claimed["job_id"], image_base64=encoded, chat_path="/c/123e4567-e89b-12d3-a456-426614174000",
                 cleanup_pending=True)
    _age(queue, claimed["job_id"], 30)
    assert queue.prune()["outputs_expired"] == 0
    assert (queue.root / claimed["job_id"] / "image.png").is_file()


def test_running_batch_jobs_are_skipped(tmp_path):
    queue = _queue(tmp_path)
    job_id = _completed(queue)
    _age(queue, job_id, 30)
    queue.jobs[job_id]["batch_id"] = "b1"

    class Batches:
        batches = {"b1": {"batch_id": "b1", "state": "running"}}
    queue._batch = Batches()
    assert queue.prune()["outputs_expired"] == 0
    Batches.batches["b1"]["state"] = "stopped"
    assert queue.prune()["outputs_expired"] == 1


def test_stale_never_delivered_request_expires_as_not_sent(tmp_path):
    queue = _queue(tmp_path)
    receipt = queue.enqueue("order-stale", "draw a cat")
    queue.jobs[receipt["job_id"]]["created_at"] -= 8 * DAY
    assert queue.prune()["stale_requests_expired"] == 1
    record = queue.status(receipt["job_id"])
    assert record["state"] == "interrupted" and "nothing reached ChatGPT" in record["error"]
    assert queue.claim(CLIENT) == {}  # Never delivered afterwards.
    assert queue.halted_job is None  # Not sent, so it does not halt the line.


def test_restart_sweeps_old_inputs_and_outputs(tmp_path):
    queue = _queue(tmp_path)
    job_id = _completed(queue)
    _age(queue, job_id, 10)
    stray = queue.root / job_id / f"input-001-{job_id}.png"
    stray.write_bytes(b"left by an older build")
    ExtensionQueue(queue.root, "test")
    assert not stray.exists()
    assert not (queue.root / job_id / "image.png").exists()


def test_expiry_after_each_completion(tmp_path):
    queue = _queue(tmp_path)
    old = _completed(queue)
    _age(queue, old, 8)
    new = _completed(queue)
    assert not (queue.root / old / "image.png").exists()
    assert (queue.root / new / "image.png").is_file()


def test_run_resume_after_expiry_never_resubmits(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    with Extension(queue) as extension:
        first = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
        _age(queue, first["job_id"], 8)
        queue.prune()
        again = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
        out.unlink()
        lost = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
    assert again["status"] == "done" and again["sha256"] == first["sha256"]
    assert lost["status"] == "failed" and lost["cause"] == "output_expired" and lost["safe_to_retry"] is False
    assert lost["sha256"] == first["sha256"] and not out.exists()
    assert len(extension.submissions) == 1


def test_owner_flag_and_connect_rejection(tmp_path):
    with pytest.raises(SystemExit):
        main(["--connect", "--output-ttl-days", "3", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        main(["--serve", "--output-ttl-days", "-1", "--data-dir", str(tmp_path)])


def test_prune_old_files_only_old_regular_images(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    old, new, text = images / "a.png", images / "b.png", images / "notes.txt"
    for path in (old, new, text):
        path.write_bytes(b"x")
    sub = images / "keep"
    sub.mkdir()
    (sub / "c.png").write_bytes(b"x")
    target = tmp_path / "outside.png"
    target.write_bytes(b"x")
    (images / "link.png").symlink_to(target)
    past = time.time() - 8 * DAY
    for path in (old, text, sub / "c.png"):
        os.utime(path, (past, past))
    assert prune_old_files(images, 7 * DAY) == 1
    assert not old.exists() and new.exists() and text.exists() and (sub / "c.png").exists() and target.exists()
    assert prune_old_files(images, 0) == 0
    assert prune_old_files(tmp_path / "missing", 7 * DAY) == 0
