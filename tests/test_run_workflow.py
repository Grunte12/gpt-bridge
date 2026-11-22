"""Offline tests for the one-call image workflow: run, auto-recovery and the non-blocking delete."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import threading
import time

from PIL import Image

from chatgpt_api.extension_bridge import ExtensionClient, ExtensionQueue, create_mcp, run_image

CLIENT = "123e4567-e89b-12d3-a456-426614174000"
CHAT = "/c/123e4567-e89b-12d3-a456-426614174000"
TAB = 17
BINDING = {"root_match": True, "exact_matching_descendant_count": 1, "expected_chars": 35,
           "observed_chars": 35, "matcher_revision": 2}


def _png(color=(40, 90, 180), size=(941, 1672)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    raw = output.getvalue()
    return base64.b64encode(raw).decode("ascii"), raw


def _queue(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", "test")
    queue.pair(CLIENT, "test", "Create image", input_protocol=4, tab_id=TAB)
    _beat(queue)
    return queue


def _beat(queue):
    queue.heartbeat(CLIENT, "test", tab_ready=True, input_protocol=4, worker_version="0.1.46",
                    content_receiver="available", tab_id=TAB)


def _start(queue):
    """What the extension does up to a bound remote chat. Returns the claimed job."""
    claimed = queue.claim(CLIENT)
    queue.phase(CLIENT, claimed["job_id"], "submit_attempted", TAB)
    queue.phase(CLIENT, claimed["job_id"], "remote_started", TAB, CHAT)
    return claimed


def _finish(queue, claimed, *, delete_ok=True, **result):
    """Capture, save and (when the job asks) delete the chat, as the extension would."""
    job_id = claimed["job_id"]
    encoded, raw = _png()
    queue.phase(CLIENT, job_id, "result_captured", TAB, CHAT)
    wants_delete = claimed.get("auto_delete_saved_chat") is True
    queue.result(CLIENT, job_id, image_base64=encoded, chat_path=CHAT, cleanup_pending=wants_delete, **result)
    if wants_delete and delete_ok:
        queue.cleanup(CLIENT, job_id, "confirmation_required")
        assert queue.claim_delete_confirmation(CLIENT, job_id) == {"confirmed": True}
        queue.cleanup(CLIENT, job_id, "deleted")
    elif wants_delete:
        queue.cleanup(CLIENT, job_id, "failed", "Native chat menu unavailable; saved image is safe")
    return raw


def _time_out(queue, job_id, reason=""):
    queue.jobs[job_id]["remote_started_at"] -= queue.jobs[job_id]["generation_timeout_seconds"] + 1
    return queue.timeout(CLIENT, job_id, CHAT, reason)


class Extension(threading.Thread):
    """A stand-in extension: claims each job once and completes it. Counts real submissions."""

    def __init__(self, queue, **finish):
        super().__init__(daemon=True)
        self.queue, self.finish, self.submissions, self.stop = queue, finish, [], threading.Event()

    def run(self):
        while not self.stop.is_set():
            _beat(self.queue)
            claimed = self.queue.claim(CLIENT)
            if claimed:
                self.submissions.append(claimed["job_id"])
                self.queue.phase(CLIENT, claimed["job_id"], "submit_attempted", TAB)
                self.queue.phase(CLIENT, claimed["job_id"], "remote_started", TAB, CHAT)
                _finish(self.queue, claimed, **self.finish)
            time.sleep(0.02)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.join(5)


def test_run_submits_once_saves_to_out_path_and_deletes_the_chat(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    with Extension(queue) as extension:
        result = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)

    assert result["status"] == "done" and result["cause"] == "ok" and result["error"] is None
    assert (result["width"], result["height"]) == (941, 1672)
    assert result["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert result["out_path"] == str(out) and result["chat_path"] == CHAT
    assert result["cleanup_status"] == "deleted"
    assert extension.submissions == [result["job_id"]]


def test_run_with_the_same_request_id_gives_one_submission(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    with Extension(queue) as extension:
        first = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
        out.unlink()
        again = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
        changed = run_image(queue, "draw a dog", str(out), "order-1", timeout_seconds=20)

    assert again["status"] == "done" and again["job_id"] == first["job_id"]
    assert again["sha256"] == first["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert len(extension.submissions) == 1
    assert [job for job in queue.jobs.values() if job.get("request_id") == "order-1"] == [queue.jobs[first["job_id"]]]
    assert changed["status"] == "failed" and changed["cause"] == "request_id_conflict"


def test_run_returns_early_with_a_resumable_job_and_never_resubmits(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    early = run_image(queue, "draw a cat", str(out), "order-1", cleanup="keep", timeout_seconds=1)

    assert (early["status"], early["cause"]) == ("running", "awaiting_worker")
    assert early["job_id"] and early["safe_to_retry"] is False and "same request_id" in early["resume"]
    assert not out.exists()
    with Extension(queue) as extension:
        resumed = run_image(queue, "draw a cat", str(out), "order-1", cleanup="keep", timeout_seconds=20)

    assert resumed["status"] == "done" and resumed["job_id"] == early["job_id"]
    assert resumed["cleanup_status"] == "kept"  # keep: the chat is never touched
    assert extension.submissions == [early["job_id"]] and len(queue.jobs) == 1


def test_hidden_tab_false_stall_is_recovered_and_named(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    with Extension(queue, stall_recovered=True) as extension:
        result = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)

    assert result["status"] == "done" and result["cause"] == "false_stall_recovered"
    assert out.exists() and len(extension.submissions) == 1
    assert queue.jobs[result["job_id"]].get("timed_out") is None


def test_timeout_with_a_finished_image_is_collected_from_the_same_chat_not_regenerated(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    assert run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=1)["status"] == "running"
    job_id = _start(queue)["job_id"]
    replacement_id = _time_out(queue, job_id)["replacement_job_id"]

    requeued = queue.timeout_cleanup(CLIENT, job_id, False, "Generated output is already visible; preserve this chat",
                                     output_visible=True)

    assert requeued["state"] == "queued" and requeued["collect_only"] is True and requeued["cleanup_status"] == "preserved"
    assert requeued["recovery_chat_path"] == CHAT and "replacement_job_id" not in requeued
    assert queue.jobs[replacement_id]["state"] == "interrupted"  # Never delivered, never regenerated.
    claimed = queue.claim(CLIENT)
    assert claimed["job_id"] == job_id and claimed["collect_only"] is True and claimed["prompt"] == "draw a cat"
    encoded, raw = _png()
    queue.result(CLIENT, job_id, image_base64=encoded, chat_path=CHAT, prompt_binding=BINDING)

    result = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
    assert result["status"] == "done" and result["cause"] == "timeout_output_recovered"
    assert result["job_id"] == job_id and result["cleanup_status"] == "preserved"
    assert out.read_bytes() == raw
    assert queue.claim(CLIENT) == {}


def test_failed_timeout_delete_is_preserved_and_the_queue_keeps_moving(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    assert run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=1)["status"] == "running"
    job_id = _start(queue)["job_id"]
    replacement_id = _time_out(queue, job_id, "no_image_returned")["replacement_job_id"]

    failed = queue.timeout_cleanup(CLIENT, job_id, False, "Native chat menu unavailable for timed-out cleanup")

    assert failed["state"] == "failed" and failed["cleanup_status"] == "preserved" and failed["delete_failed"] is True
    assert failed["chat_path"] == CHAT
    status = queue.status()
    assert status["line_halted"] is None and status["scheduler"]["in_flight_or_cleanup"] == 0
    other = queue.submit("another agent's image", "Create image")  # New work is admitted at once.
    assert other["state"] == "queued"
    restarted = ExtensionQueue(queue.root, "test")  # Pairing is never refused, even after a restart.
    restarted.pair(CLIENT, "test", "Create image", input_protocol=4, tab_id=TAB)
    with Extension(queue) as extension:  # The one replacement carries the request; run follows it by itself.
        result = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
        deadline = time.monotonic() + 5
        while len(extension.submissions) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)

    assert result["status"] == "done" and result["job_id"] == replacement_id
    assert result["replaced_job_ids"] == [job_id]
    assert extension.submissions == [replacement_id, other["job_id"]]


def test_legacy_failed_timeout_delete_on_disk_no_longer_blocks(tmp_path):
    queue = _queue(tmp_path)
    job_id = queue.submit("draw a cat", "Create image")["job_id"]
    _start(queue)
    _time_out(queue, job_id)
    queue.timeout_cleanup(CLIENT, job_id, False, "exact_chat_guard")
    record = dict(queue.jobs[job_id], cleanup_status="timeout_delete_failed")
    (queue.root / job_id / "state.json").write_text(json.dumps(record))

    restarted = ExtensionQueue(queue.root, "test")

    assert restarted.jobs[job_id]["cleanup_status"] == "preserved"
    assert restarted.pair(CLIENT, "test", "Create image", input_protocol=4, tab_id=TAB)["paired"] is True


def test_hidden_unchecked_timeout_keeps_the_chat_without_a_blind_replacement(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    assert run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=1)["status"] == "running"
    job_id = _start(queue)["job_id"]
    timed_out = _time_out(queue, job_id, "page_hidden_unverified")

    assert timed_out["cleanup_status"] == "preserved" and "replacement_job_id" not in timed_out
    result = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=5)
    assert result["status"] == "failed" and result["cause"] == "stalled_hidden_tab"
    assert result["safe_to_retry"] is False and result["chat_path"] == CHAT and not out.exists()
    assert queue.status()["line_halted"] is None


def test_run_names_the_cause_of_each_failure(tmp_path):
    cases = [("Not submitted. Owner action required: complete verification in ChatGPT. Nothing was submitted.",
              "verification_required", False),
             ("Not submitted. ChatGPT composer unavailable. Nothing was submitted.", "not_submitted", True),
             ("Submission attempted. Displayed image could not be read; preserve the existing chat", "output_unreadable", False)]
    for index, (error, cause, safe) in enumerate(cases):
        queue, out = _queue(tmp_path / str(index)), tmp_path / f"{index}.png"
        run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=1)
        claimed = queue.claim(CLIENT)
        if error.startswith("Submission attempted"):
            queue.phase(CLIENT, claimed["job_id"], "submit_attempted", TAB)
            queue.phase(CLIENT, claimed["job_id"], "remote_started", TAB, CHAT)
        queue.result(CLIENT, claimed["job_id"], error=error)
        result = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=5)
        assert (result["status"], result["cause"], result["safe_to_retry"]) == ("failed", cause, safe)
        assert result["error"] == error and not out.exists()

    queue = _queue(tmp_path / "chatgpt")
    run_image(queue, "draw a cat", str(tmp_path / "n.png"), "order-1", timeout_seconds=1)
    job_id = _start(queue)["job_id"]
    queue.jobs[job_id].update(mode="edit")  # No replacement for edits: the timeout is the final answer.
    _time_out(queue, job_id, "no_image_returned")
    queue.timeout_cleanup(CLIENT, job_id, True)
    result = run_image(queue, "draw a cat", str(tmp_path / "n.png"), "order-1", timeout_seconds=5)
    assert (result["cause"], result["safe_to_retry"], result["cleanup_status"]) == ("chatgpt_no_image", True, "deleted")


def test_saved_chat_delete_failure_still_returns_the_image(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    with Extension(queue, delete_ok=False):
        result = run_image(queue, "draw a cat", str(out), "order-1", timeout_seconds=20)
        assert queue.submit("next image", "Create image")["state"] == "queued"

    assert result["status"] == "done" and result["cause"] == "delete_failed_preserved"
    assert result["cleanup_status"] == "preserved" and result["delete_failed"] is True and out.exists()


def test_run_rejects_a_bad_out_path_or_offline_extension_before_any_submission(tmp_path):
    queue = _queue(tmp_path)
    for bad in ("relative.png", str(tmp_path / "missing" / "cat.png"), str(tmp_path)):
        result = run_image(queue, "draw a cat", bad, "order-1")
        assert result["status"] == "failed" and result["cause"] == "invalid_out_path" and result["safe_to_retry"] is True
    assert not any(job.get("request_id") for job in queue.jobs.values())
    offline = ExtensionQueue(tmp_path / "offline", "test")
    result = run_image(offline, "draw a cat", str(tmp_path / "cat.png"), "order-1")
    assert (result["status"], result["cause"], result["safe_to_retry"]) == ("failed", "extension_offline", True)


def test_mcp_run_tool_returns_one_receipt(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"
    server = create_mcp(queue)
    schema = next(tool for tool in server._tool_manager.list_tools() if tool.name == "run").parameters
    assert set(schema["required"]) == {"prompt", "out_path", "request_id"}
    assert schema["properties"]["cleanup"]["default"] == "delete_on_success"
    with Extension(queue):
        reply = asyncio.run(server.call_tool("run", {"prompt": "draw a cat", "out_path": str(out),
                                                    "request_id": "order-1", "timeout_seconds": 20}))
    result = json.loads(reply[0].text)
    assert {"status", "out_path", "width", "height", "sha256", "job_id", "chat_path", "cleanup_status",
            "error", "cause", "safe_to_retry"} <= set(result)
    assert result["status"] == "done" and out.exists()


def test_run_works_through_the_shared_worker_client(tmp_path):
    queue, out = _queue(tmp_path), tmp_path / "cat.png"

    class Client(ExtensionClient):  # Same wire shape as the loopback routes, without a socket.
        def call(self, action, data, timeout=10):
            routes = {"status": lambda: queue.status(**data), "enqueue": lambda: queue.enqueue(**data),
                      "wait": lambda: queue.wait_for_job(data["job_id"], data.get("timeout_seconds", 120))}
            return json.loads(json.dumps(routes[action]()))

    with Extension(queue) as extension:
        result = run_image(Client("unused-local-token"), "draw a cat", str(out), "order-1", cleanup="keep", timeout_seconds=20)

    assert result["status"] == "done" and result["cleanup_status"] == "kept" and out.exists()
    assert queue.jobs[result["job_id"]]["cleanup_requested"] == "keep" and len(extension.submissions) == 1


def test_overlapping_saves_queue_and_write_once(tmp_path):
    import hashlib, threading
    from chatgpt_api.extension_bridge import save_output
    target, raw = tmp_path / "out.png", b"image-bytes" * 1000
    digest, writes, errors = hashlib.sha256(raw).hexdigest(), [], []

    def slow_write(path, data):
        writes.append(path)
        path.write_bytes(data)

    def call():
        try:
            save_output(target, raw, digest, "job1", slow_write)
        except Exception as error:  # pragma: no cover - the test fails on any error
            errors.append(error)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and len(writes) == 1 and target.read_bytes() == raw
    assert not list(tmp_path.glob(".*.tmp"))
