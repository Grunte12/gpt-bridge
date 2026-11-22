"""Offline tests for durable image requests queued behind native batches."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json

import pytest
from PIL import Image

from chatgpt_api.extension_bridge import ExtensionClient, ExtensionQueue, create_mcp, make_handler


CLIENT = "123e4567-e89b-12d3-a456-426614174000"
TOKEN = "synthetic-local-token-with-enough-length"


def item(sid):
    prompt = "prompt " + sid
    return {"scenario_id": sid, "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}


@pytest.fixture
def ready(tmp_path):
    dest, marks = tmp_path / "raw", tmp_path / "receipts"
    dest.mkdir()
    marks.mkdir()
    rows = [item("batch-a"), item("batch-b")]
    (tmp_path / "prompts.json").write_text(json.dumps(rows))
    (tmp_path / "generation_log.tsv").write_text("scenario_id\tstatus\n")
    queue = ExtensionQueue(tmp_path / "queue", "test", batch_allowed_runs=[tmp_path])
    queue.pair(CLIENT, "test", "Create image", input_protocol=3)
    queue.heartbeat(CLIENT, "test", tab_ready=True, input_protocol=3)
    queue.batch_start("batch-one", rows, str(dest), str(marks))
    return queue, dest, marks


def _png(color=(50, 90, 130)):
    output = io.BytesIO()
    Image.new("RGB", (512, 512), color).save(output, format="PNG")
    return output.getvalue()


def test_enqueue_is_idempotent_by_request_id_and_rejects_changed_payload(ready):
    queue, _dest, _marks = ready
    first = queue.enqueue("req-1", "Make a warm cafe illustration.")
    again = queue.enqueue("req-1", "Make a warm cafe illustration.")

    assert first["job_id"] == again["job_id"]
    assert first["state"] == "waiting_for_batch"
    assert first["request_id"] == "req-1"
    assert first["payload_hash"] == queue.jobs[first["job_id"]]["payload_hash"]
    with pytest.raises(ValueError, match="different payload"):
        queue.enqueue("req-1", "Make a different cafe illustration.")
    assert len([job for job in queue.jobs.values() if job.get("request_id") == "req-1"]) == 1


def test_simultaneous_same_request_id_accepts_exactly_one_job(ready):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    queue, _dest, _marks = ready
    barrier = Barrier(6)

    def enqueue(_index):
        barrier.wait()
        return queue.enqueue("req-race", "Same concurrent request.")

    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(pool.map(enqueue, range(6)))

    assert len({receipt["job_id"] for receipt in receipts}) == 1
    assert len([job for job in queue.jobs.values() if job.get("request_id") == "req-race"]) == 1


def test_batch_finishes_before_waiters_and_releases_them_fifo(ready):
    queue, _dest, _marks = ready
    record = queue._batch.batches["batch-one"]
    queue._batch.tick(record)
    first = queue.enqueue("req-1", "First deferred image.")
    second = queue.enqueue("req-2", "Second deferred image.")

    active = queue.claim(CLIENT)
    assert active["job_id"] == record["progress"][0]["job_id"]
    assert queue.claim(CLIENT) == {}
    queue.result(CLIENT, active["job_id"], image_base64=base64.b64encode(_png()).decode())
    queue._batch.tick(record)
    assert record["progress"][0]["state"] == "saved"
    assert record["progress"][1]["state"] == "reserved"
    assert queue.jobs[first["job_id"]]["state"] == "waiting_for_batch"

    active = queue.claim(CLIENT)
    assert active["job_id"] == record["progress"][1]["job_id"]
    queue.result(CLIENT, active["job_id"], image_base64=base64.b64encode(_png((90, 40, 10))).decode())
    queue._batch.tick(record)
    assert record["state"] == "complete"

    released = queue.claim(CLIENT)
    assert released["job_id"] == first["job_id"]
    assert queue.jobs[first["job_id"]]["state"] == "claimed"
    queue.result(CLIENT, released["job_id"], image_base64=base64.b64encode(_png((10, 90, 40))).decode())
    released = queue.claim(CLIENT)
    assert released["job_id"] == second["job_id"]


@pytest.mark.parametrize("blocker", ["stopped", "missing"])
def test_stopped_or_missing_batch_blocker_never_releases_waiter(ready, blocker):
    queue, _dest, _marks = ready
    queued = queue.enqueue("req-held", "Stay blocked.")
    record = queue._batch.batches["batch-one"]
    if blocker == "stopped":
        queue._batch._stop(record, "synthetic failure")
    else:
        del queue._batch.batches["batch-one"]

    assert queue.claim(CLIENT) == {}
    assert queue.jobs[queued["job_id"]]["state"] == "waiting_for_batch"


def test_restart_stops_batch_but_preserves_waiter_without_delivery(ready):
    queue, _dest, _marks = ready
    record = queue._batch.batches["batch-one"]
    queue._batch.tick(record)
    queued = queue.enqueue("req-restart", "Remain pinned after restart.")

    restarted = ExtensionQueue(queue.root, "test", batch_allowed_runs=queue.batch_allowed_runs)
    assert restarted.batch_status("batch-one")["state"] == "stopped"
    assert restarted.jobs[queued["job_id"]]["state"] == "waiting_for_batch"
    restarted.heartbeat(CLIENT, "test", tab_ready=True, input_protocol=3)
    assert restarted.claim(CLIENT) == {}
    assert restarted.jobs[queued["job_id"]]["state"] == "waiting_for_batch"
    assert restarted.jobs[record["progress"][0]["job_id"]]["state"] == "interrupted"


def test_restart_rejects_different_client_but_original_client_can_rebind(ready):
    queue, _dest, _marks = ready
    queued = queue.enqueue("req-owner", "Stay with the original extension owner.")
    restarted = ExtensionQueue(queue.root, "test", batch_allowed_runs=queue.batch_allowed_runs)

    other_client = "123e4567-e89b-12d3-a456-426614174001"
    with pytest.raises(ValueError, match="finish the current job"):
        restarted.pair(other_client, "test", "Create image", input_protocol=3)
    assert restarted.jobs[queued["job_id"]]["client_id"] == CLIENT

    restarted.heartbeat(CLIENT, "test", tab_ready=True, input_protocol=3)
    assert restarted.client["client_id"] == CLIENT


def test_completed_blocker_and_waiters_survive_restart_in_fifo_order(ready):
    queue, _dest, _marks = ready
    first = queue.enqueue("req-first", "First after completed batch.")
    second = queue.enqueue("req-second", "Second after completed batch.")
    record = queue._batch.batches["batch-one"]
    record["state"] = "complete"
    queue._batch._save(record)

    restarted = ExtensionQueue(queue.root, "test", batch_allowed_runs=queue.batch_allowed_runs)
    assert restarted.batch_status("batch-one")["state"] == "complete"
    restarted.heartbeat(CLIENT, "test", tab_ready=True, input_protocol=3)
    assert restarted.claim(CLIENT)["job_id"] == first["job_id"]
    restarted.result(CLIENT, first["job_id"], image_base64=base64.b64encode(_png((10, 90, 40))).decode())
    assert restarted.claim(CLIENT)["job_id"] == second["job_id"]


def test_claim_fifo_uses_durable_sequence_when_wall_clock_moves_backward(ready, monkeypatch):
    queue, _dest, _marks = ready
    times = iter((1000.0, 100.0))
    monkeypatch.setattr("chatgpt_api.extension_bridge.time.time", lambda: next(times, 50.0))
    first = queue.enqueue("req-clock-first", "Accepted first.")
    second = queue.enqueue("req-clock-second", "Accepted second.")
    record = queue._batch.batches["batch-one"]
    record["state"] = "complete"
    queue._batch._save(record)

    assert queue.jobs[first["job_id"]]["created_at"] > queue.jobs[second["job_id"]]["created_at"]
    assert queue.claim(CLIENT)["job_id"] == first["job_id"]


def test_enqueue_reuses_original_pinned_image_after_source_deletion(ready, tmp_path):
    queue, _dest, _marks = ready
    source = tmp_path / "reference.png"
    original = _png()
    source.write_bytes(original)
    request = queue.enqueue("req-image", "Use this reference.", images=[{
        "path": str(source), "role": "reference", "description": "color reference",
    }])
    source.unlink()

    duplicate = queue.enqueue("req-image", "Use this reference.", images=[{
        "path": str(source), "role": "reference", "description": "color reference",
    }])
    record = queue._batch.batches["batch-one"]
    record["state"] = "complete"
    queue._batch._save(record)
    claimed = queue.claim(CLIENT)
    assert duplicate["job_id"] == request["job_id"] == claimed["job_id"]
    assert base64.b64decode(claimed["images"][0]["data_base64"]) == original
    assert claimed["images"][0]["sha256"] == hashlib.sha256(original).hexdigest()


def test_save_failure_does_not_durably_accept_request(ready, monkeypatch):
    queue, _dest, _marks = ready

    def fail_save(_job):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(queue, "_save", fail_save)
    with pytest.raises(OSError, match="disk failure"):
        queue.enqueue("req-save-fail", "Must not be accepted.")
    assert not any(job.get("request_id") == "req-save-fail" for job in queue.jobs.values())
    assert not list(queue.root.glob("*/state.json"))


def test_enqueue_respects_existing_queue_capacity(ready):
    queue, _dest, _marks = ready
    record = queue._batch.batches["batch-one"]
    queue._batch.tick(record)
    for index in range(9):
        queue.enqueue(f"req-cap-{index}", f"Capacity item {index}.")
    with pytest.raises(ValueError, match="queue is full"):
        queue.enqueue("req-cap-overflow", "Must be rejected.")
    assert len([job for job in queue.jobs.values()
                if job["state"] not in {"complete", "failed", "interrupted"}]) == 10


def _request(handler_type, path, payload, *, token=TOKEN):
    body = json.dumps(payload).encode()
    handler = object.__new__(handler_type)
    handler.headers = {"Host": "127.0.0.1:18767", "Origin": "",
                       "Authorization": f"Bearer {token}", "Content-Length": str(len(body))}
    handler.path = path
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    codes = []
    handler.send_response = codes.append
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    handler.do_POST()
    return codes[-1], json.loads(handler.wfile.getvalue())


def test_enqueue_http_and_mcp_routes_share_idempotent_request(ready):
    queue, _dest, _marks = ready
    handler = make_handler(queue, TOKEN, 18767)
    payload = {"request_id": "req-transport", "prompt": "One transport request."}
    assert _request(handler, "/agent/enqueue", payload, token="wrong")[0] == 401
    status, receipt = _request(handler, "/agent/enqueue", payload)
    assert status == 200 and receipt["state"] == "waiting_for_batch"

    result = asyncio.run(create_mcp(queue).call_tool("enqueue", payload))
    assert receipt["job_id"] in result[0].text
    assert len([job for job in queue.jobs.values() if job.get("request_id") == "req-transport"]) == 1


def test_pending_request_receipts_and_active_batch_summary_are_compact_and_durable(ready):
    queue, _dest, _marks = ready
    from chatgpt_api.extension_bridge import compact_status

    summary = compact_status(queue.status())
    assert summary["active_batch"] == {
        "batch_id": "batch-one", "state": "running", "total": 2,
        "saved": 0, "reserved": 0, "untouched": 2,
    }
    assert summary["admission"] == "waiting_for_batch"
    assert summary["scheduler"]["in_flight_or_cleanup"] == 0
    assert summary["scheduler"]["waiting_for_batch"] == 0

    queued = queue.enqueue("req-receipt", "Expose stable receipt metadata.")
    expected = {"request_id": "req-receipt", "payload_hash": queued["payload_hash"],
                "blocked_by_batch": "batch-one"}
    job_receipt = compact_status(queue.status(queued["job_id"]))
    wait_receipt = queue.wait_for_job(queued["job_id"], timeout_seconds=1)
    assert {key: job_receipt[key] for key in expected} == expected
    assert {key: wait_receipt[key] for key in expected} == expected
    assert wait_receipt["wait_timed_out"] is True

    server = create_mcp(queue)
    job_result = asyncio.run(server.call_tool("job", {"job_id": queued["job_id"]}))
    wait_result = asyncio.run(server.call_tool("wait", {"job_id": queued["job_id"], "timeout_seconds": 1}))
    for key, value in expected.items():
        assert key in job_result[0].text and value in job_result[0].text
        assert key in wait_result[0].text and value in wait_result[0].text


def test_client_enqueue_forwards_stable_request_and_pinned_input_arguments():
    client = ExtensionClient(TOKEN)
    calls = []
    client.call = lambda action, payload: calls.append((action, payload)) or {"state": "waiting_for_batch"}
    image = {"path": "/tmp/reference.png", "role": "source", "description": "edit source"}

    assert client.enqueue("req-client", "Retouch the source.", [image], mode="edit") == {
        "state": "waiting_for_batch",
    }
    assert calls == [("enqueue", {"request_id": "req-client", "prompt": "Retouch the source.",
                                  "mode": "edit", "images": [image]})]


