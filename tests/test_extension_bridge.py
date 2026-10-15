"""Offline tests for the opt-in localhost image-extension queue."""

import base64
import hashlib
import io
import json
import stat
import uuid

import pytest
from PIL import Image

from chatgpt_api.extension_bridge import ExtensionQueue, MAX_IMAGE, main, make_handler


ACCOUNT = "second"
CLIENT_ID = "123e4567-e89b-12d3-a456-426614174000"
TOKEN = "synthetic-local-token-with-enough-length"
EXTENSION_ORIGIN = "chrome-extension://" + "a" * 32


def _paired_queue(tmp_path, *, account=ACCOUNT, client_id=CLIENT_ID):
    queue = ExtensionQueue(tmp_path / "extension-data", account)
    queue.pair(client_id, account, visible_model="Create image")
    return queue


def _png_base64(size=(512, 512)):
    image = Image.new("RGB", size, (40, 90, 180))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii"), buffer.getvalue()


def _call_post(handler_type, path, payload, *, token=TOKEN, origin=EXTENSION_ORIGIN,
               host="127.0.0.1:8767", content_length=None):
    body = json.dumps(payload).encode("utf-8")
    handler = object.__new__(handler_type)
    handler.headers = {
        "Host": host,
        "Origin": origin,
        "Authorization": f"Bearer {token}" if token is not None else "",
        "Content-Length": str(content_length if content_length is not None else len(body)),
    }
    handler.path = path
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    handler.do_POST()
    return statuses[-1], json.loads(handler.wfile.getvalue())


def test_pairing_checks_account_and_client_identity(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)

    with pytest.raises(ValueError, match="identity mismatch"):
        queue.pair(CLIENT_ID, "other-account")
    with pytest.raises(ValueError, match="identity mismatch"):
        queue.pair("not-a-uuid", ACCOUNT)

    paired = queue.pair(CLIENT_ID, ACCOUNT)
    assert paired["paired"] is True
    assert queue.status()["paired"] is True
    assert queue.status()["tab_ready"] is True


def test_pair_status_reports_owner_confirmed_visible_model(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)

    queue.pair(CLIENT_ID, ACCOUNT, visible_model="Create image")

    assert queue.status()["visible_model"] == "Create image"
    assert queue.status()["tab_ready"] is True


def test_heartbeat_reconnects_original_client_and_requires_ready_native_mode(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, visible_model="Create image")

    offline = queue.heartbeat(CLIENT_ID, ACCOUNT, "Create image", tab_ready=False)
    assert offline["paired"] is True
    assert offline["tab_ready"] is False
    with pytest.raises(ValueError, match="ready|image mode"):
        queue.submit("Do not dispatch", "Create image")

    ready = queue.heartbeat(CLIENT_ID, ACCOUNT, "Create image", tab_ready=True)
    assert ready["paired"] is True
    assert ready["tab_ready"] is True
    assert ready["visible_model"] == "Create image"


def test_heartbeat_rejects_wrong_identity_account_mode_and_ready_type(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, visible_model="Create image")

    for client_id, account, model, ready in [
        (str(uuid.uuid4()), ACCOUNT, "Create image", True),
        (CLIENT_ID, "main", "Create image", True),
        (CLIENT_ID, ACCOUNT, "GPT-6 Thinking", True),
        (CLIENT_ID, ACCOUNT, "Create image", "true"),
    ]:
        with pytest.raises(ValueError):
            queue.heartbeat(client_id, account, model, tab_ready=ready)


def test_extension_runtime_rejects_main_account_before_creating_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        "sys.argv", ["gpt-bridge-extension", "--account", "main", "--data-dir", str(data_dir)]
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert not data_dir.exists()


def test_claim_is_at_most_once_and_public_status_hides_private_fields(tmp_path):
    queue = _paired_queue(tmp_path)
    job = queue.submit("Draw a green pear.", "GPT-6 Pro")
    job_id = job["job_id"]

    claimed = queue.claim(CLIENT_ID)
    assert claimed == {
        "job_id": job_id,
        "prompt": "Draw a green pear.",
        "expected_model": "GPT-6 Pro",
    }
    assert queue.claim(CLIENT_ID) == {}
    assert "prompt" not in job
    public = queue.status(job_id)
    assert public["state"] == "claimed"
    assert "prompt" not in public
    assert "client_id" not in public


def test_wrong_client_cannot_claim_or_submit_result(tmp_path):
    queue = _paired_queue(tmp_path)
    job = queue.submit("A small blue bird.", "GPT-6 Pro")

    with pytest.raises(ValueError, match="not paired"):
        queue.claim(str(uuid.uuid4()))
    queue.claim(CLIENT_ID)
    with pytest.raises(ValueError, match="not paired"):
        queue.result(str(uuid.uuid4()), job["job_id"], error="forged")


def test_restart_marks_uncertain_claim_interrupted_without_redelivery(tmp_path):
    root = tmp_path / "queue"
    queue = ExtensionQueue(root, ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT)
    submitted = queue.submit("One image only.", "GPT-6 Pro")
    assert queue.claim(CLIENT_ID)["job_id"] == submitted["job_id"]

    restarted = ExtensionQueue(root, ACCOUNT)
    status = restarted.status(submitted["job_id"])
    assert status["state"] == "interrupted"
    assert "inspect ChatGPT" in status["error"]
    # A heartbeat reconnects the same client but never replays interrupted work.
    assert restarted.client is None
    assert restarted.status()["tab_ready"] is False
    recovered = restarted.heartbeat(CLIENT_ID, ACCOUNT, "Create image", tab_ready=True)
    assert recovered["paired"] is True and recovered["tab_ready"] is True
    assert restarted.claim(CLIENT_ID) == {}


def test_state_endpoint_returns_restarted_job_only_to_its_original_client(tmp_path):
    root = tmp_path / "queue"
    queue = ExtensionQueue(root, ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT)
    submitted = queue.submit("One image only.", "GPT-6 Pro")
    queue.claim(CLIENT_ID)
    restarted = ExtensionQueue(root, ACCOUNT)
    handler = make_handler(restarted, TOKEN, 8767)

    status, state = _call_post(
        handler, "/state", {"client_id": CLIENT_ID, "job_id": submitted["job_id"]}
    )
    assert status == 200
    assert state["job_id"] == submitted["job_id"]
    assert state["state"] == "interrupted"
    assert "prompt" not in state and "client_id" not in state
    assert restarted.client is None

    status, _ = _call_post(
        handler, "/state", {"client_id": str(uuid.uuid4()), "job_id": submitted["job_id"]}
    )
    assert status == 400


def test_http_heartbeat_reconnects_without_replaying_and_reports_only_public_status(tmp_path):
    root = tmp_path / "queue"
    queue = ExtensionQueue(root, ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, visible_model="Create image")
    submitted = queue.submit("One image only.", "Create image")
    queue.claim(CLIENT_ID)
    restarted = ExtensionQueue(root, ACCOUNT)
    handler = make_handler(restarted, TOKEN, 8767)

    status, heartbeat = _call_post(handler, "/heartbeat", {
        "client_id": CLIENT_ID, "account": ACCOUNT,
        "visible_model": "Create image", "tab_ready": True,
    })
    assert status == 200
    assert heartbeat["paired"] is True and heartbeat["tab_ready"] is True
    assert restarted.status(submitted["job_id"])["state"] == "interrupted"
    assert restarted.claim(CLIENT_ID) == {}
    assert "token" not in heartbeat and "client_id" not in heartbeat

    status, _ = _call_post(handler, "/heartbeat", {
        "client_id": str(uuid.uuid4()), "account": ACCOUNT,
        "visible_model": "Create image", "tab_ready": True,
    })
    assert status == 400


def test_complete_result_saves_private_image_and_public_metadata(tmp_path):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Blue bird on a branch.", "GPT-6 Pro")
    job_id = submitted["job_id"]
    queue.claim(CLIENT_ID)
    image_base64, raw = _png_base64()

    complete = queue.result(CLIENT_ID, job_id, image_base64=image_base64)

    assert complete["state"] == "complete"
    assert complete["dimensions"] == [512, 512]
    assert complete["sha256"] == hashlib.sha256(raw).hexdigest()
    assert "prompt" not in complete and "client_id" not in complete
    path = queue.root / job_id / "image.png"
    assert path.read_bytes() == raw
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((queue.root / job_id / "state.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(queue.root.stat().st_mode) == 0o700


def test_failed_result_is_terminal_and_error_is_bounded(tmp_path):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Make one image.", "GPT-6 Pro")
    queue.claim(CLIENT_ID)

    failed = queue.result(CLIENT_ID, submitted["job_id"], error="x" * 900)

    assert failed["state"] == "failed"
    assert len(failed["error"]) == 500
    assert queue.claim(CLIENT_ID) == {}


def test_invalid_or_oversized_image_payload_is_rejected_without_completing_job(tmp_path, monkeypatch):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Make one image.", "GPT-6 Pro")
    queue.claim(CLIENT_ID)

    with pytest.raises((ValueError, OSError)):
        queue.result(CLIENT_ID, submitted["job_id"], image_base64="not base64!")
    tiny_image, _ = _png_base64((64, 64))
    with pytest.raises(ValueError, match="at least 512px"):
        queue.result(CLIENT_ID, submitted["job_id"], image_base64=tiny_image)

    monkeypatch.setattr("chatgpt_api.extension_bridge.MAX_IMAGE", 8)
    with pytest.raises(ValueError, match="oversized"):
        queue.result(CLIENT_ID, submitted["job_id"], image_base64="A" * 32)
    assert queue.status(submitted["job_id"])["state"] == "claimed"


def test_submit_enforces_prompt_model_and_single_active_job_limits(tmp_path):
    queue = _paired_queue(tmp_path)

    for prompt in ("", "  ", "x" * 16001):
        with pytest.raises(ValueError, match="prompt"):
            queue.submit(prompt, "GPT-6 Pro")
    for model in ("", "  ", "x" * 101):
        with pytest.raises(ValueError, match="expected_model"):
            queue.submit("Draw one image.", model)

    job = queue.submit("Draw one image.", " GPT-6 Pro ")
    assert job["expected_model"] == "GPT-6 Pro"
    with pytest.raises(ValueError, match="one image job at a time"):
        queue.submit("A second image.", "GPT-6 Pro")


def test_resolve_marks_queued_work_interrupted_without_claiming_it(tmp_path):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Uncertain upstream state.", "GPT-6 Pro")

    resolved = queue.resolve(submitted["job_id"])

    assert resolved["state"] == "interrupted"
    assert "no automatic resubmission" in resolved["error"]
    assert queue.claim(CLIENT_ID) == {}


def test_local_http_handler_rejects_bad_auth_host_and_origin(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    handler = make_handler(queue, TOKEN, 8767)
    payload = {"client_id": CLIENT_ID, "account": ACCOUNT}

    status, _ = _call_post(handler, "/pair", payload, token="wrong-token")
    assert status == 401
    status, _ = _call_post(handler, "/pair", payload, origin="https://attacker.example")
    assert status == 403
    status, _ = _call_post(handler, "/pair", payload, host="attacker.example:8767")
    assert status == 403
    assert queue.status()["paired"] is False


def test_local_http_handler_pairs_and_claims_with_owner_extension_origin(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    handler = make_handler(queue, TOKEN, 8767)
    status, result = _call_post(
        handler,
        "/pair",
        {"client_id": CLIENT_ID, "account": ACCOUNT, "visible_model": "Create image"},
    )
    assert status == 200 and result["paired"] is True
    assert queue.status()["visible_model"] == "Create image"

    submitted = queue.submit("Render one image.", "GPT-6 Pro")
    status, claimed = _call_post(handler, "/next", {"client_id": CLIENT_ID})
    assert status == 200
    assert claimed["job_id"] == submitted["job_id"]
    assert "prompt" in claimed


def test_local_http_handler_rejects_oversized_and_unknown_routes(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    handler = make_handler(queue, TOKEN, 8767)

    status, body = _call_post(handler, "/unknown", {"x": 1})
    assert status == 404
    assert body["error"] == "unknown route"

    # Content-Length is validated before JSON parsing or queue mutation.
    status, body = _call_post(handler, "/pair", {}, token=TOKEN)
    assert status == 400
    assert "invalid request" in body["error"]

    status, body = _call_post(
        handler,
        "/pair",
        {},
        content_length=MAX_IMAGE * 4 // 3 + 4097,
    )
    assert status == 413
    assert body["error"] == "request too large"
