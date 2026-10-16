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
    queued = queue.submit("Prepare a fresh-chat image.", "Create image")
    assert queued["state"] == "queued"

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
    job = queue.submit("Draw a green pear.", "Create image")
    job_id = job["job_id"]

    claimed = queue.claim(CLIENT_ID)
    assert claimed == {
        "job_id": job_id,
        "prompt": "Draw a green pear.",
        "expected_model": "Create image",
    }
    assert queue.claim(CLIENT_ID) == {}
    assert "prompt" not in job
    public = queue.status(job_id)
    assert public["state"] == "claimed"
    assert "prompt" not in public
    assert "client_id" not in public


def test_wrong_client_cannot_claim_or_submit_result(tmp_path):
    queue = _paired_queue(tmp_path)
    job = queue.submit("A small blue bird.", "Create image")

    with pytest.raises(ValueError, match="not paired"):
        queue.claim(str(uuid.uuid4()))
    queue.claim(CLIENT_ID)
    with pytest.raises(ValueError, match="not paired"):
        queue.result(str(uuid.uuid4()), job["job_id"], error="forged")


def test_restart_marks_uncertain_claim_interrupted_without_redelivery(tmp_path):
    root = tmp_path / "queue"
    queue = ExtensionQueue(root, ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT)
    submitted = queue.submit("One image only.", "Create image")
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
    submitted = queue.submit("One image only.", "Create image")
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
    submitted = queue.submit("Blue bird on a branch.", "Create image")
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


def _complete_image_job(queue, *, cleanup_pending=True):
    submitted = queue.submit("A saved image for cleanup testing.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, raw = _png_base64()
    complete = queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                            cleanup_pending=cleanup_pending)
    return submitted["job_id"], raw, complete


def test_cleanup_requires_confirmation_before_delete_and_preserves_image(tmp_path):
    queue = _paired_queue(tmp_path)
    job_id, raw, complete = _complete_image_job(queue)
    image_path = queue.root / job_id / "image.png"
    digest = hashlib.sha256(raw).hexdigest()

    assert complete["state"] == "complete"
    assert complete["cleanup_status"] == "pending"
    with pytest.raises(ValueError, match="confirmation step"):
        queue.cleanup(CLIENT_ID, job_id, "deleted")
    confirmation = queue.cleanup(CLIENT_ID, job_id, "confirmation_required")
    assert confirmation["cleanup_status"] == "confirmation_required"
    with pytest.raises(ValueError, match="already pending"):
        queue.cleanup(CLIENT_ID, job_id, "confirmation_required")
    deleted = queue.cleanup(CLIENT_ID, job_id, "deleted")

    assert deleted["state"] == "complete"
    assert deleted["cleanup_status"] == "deleted"
    assert deleted["sha256"] == digest
    assert image_path.read_bytes() == raw
    with pytest.raises(ValueError, match="cleanup is not pending"):
        queue.cleanup(CLIENT_ID, job_id, "deleted")


@pytest.mark.parametrize("initial_cleanup", ["pending", "confirmation_required"])
def test_failed_cleanup_persists_error_and_complete_image_across_restart(tmp_path, initial_cleanup):
    root = tmp_path / "queue"
    queue = _paired_queue(root)
    data_root = queue.root
    job_id, raw, _ = _complete_image_job(queue)
    digest = hashlib.sha256(raw).hexdigest()
    if initial_cleanup == "confirmation_required":
        queue.cleanup(CLIENT_ID, job_id, "confirmation_required")

    failed = queue.cleanup(CLIENT_ID, job_id, "failed", "synthetic deletion failure")
    assert failed["state"] == "complete"
    assert failed["cleanup_status"] == "failed"
    assert failed["cleanup_error"] == "synthetic deletion failure"
    assert failed["sha256"] == digest

    restarted = ExtensionQueue(data_root, ACCOUNT)
    persisted = restarted.status(job_id)
    assert persisted["state"] == "complete"
    assert persisted["cleanup_status"] == "failed"
    assert persisted["cleanup_error"] == "synthetic deletion failure"
    assert persisted["sha256"] == digest
    assert (data_root / job_id / "image.png").read_bytes() == raw
    restarted.pair(CLIENT_ID, ACCOUNT)
    with pytest.raises(ValueError, match="cleanup is not pending"):
        restarted.cleanup(CLIENT_ID, job_id, "deleted")


def test_delete_authorization_claim_is_durable_single_use_and_chat_bound(tmp_path):
    root = tmp_path / "queue"
    queue = _paired_queue(root)
    submitted = queue.submit("Image with a native conversation.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, raw = _png_base64()
    chat_path = "/c/123e4567-e89b-12d3-a456-426614174000"
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                 cleanup_pending=True, chat_path=chat_path)
    queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")

    assert queue.status(submitted["job_id"])["chat_path"] == chat_path
    with pytest.raises(ValueError, match="actual owner confirmation"):
        queue.confirm_delete(submitted["job_id"], "true")
    assert queue.claim_delete_confirmation(CLIENT_ID, submitted["job_id"]) == {"confirmed": False}
    authorized = queue.confirm_delete(submitted["job_id"], True)
    assert authorized["cleanup_confirmation"] == "requested"
    with pytest.raises(ValueError, match="single-use"):
        queue.confirm_delete(submitted["job_id"], True)

    # A dialog for another client or a non-awaiting job cannot take the authorization.
    with pytest.raises(ValueError, match="not paired"):
        queue.claim_delete_confirmation(str(uuid.uuid4()), submitted["job_id"])
    assert queue.claim_delete_confirmation(CLIENT_ID, submitted["job_id"]) == {"confirmed": True}
    assert queue.status(submitted["job_id"])["cleanup_confirmation"] == "consumed"
    restarted = ExtensionQueue(root / "extension-data", ACCOUNT)
    restarted.pair(CLIENT_ID, ACCOUNT)
    with pytest.raises(ValueError, match="only the original saved-image dialog"):
        restarted.claim_delete_confirmation(CLIENT_ID, submitted["job_id"])
    with pytest.raises(ValueError, match="saved-image chat"):
        restarted.confirm_delete(submitted["job_id"], True)
    assert (root / "extension-data" / submitted["job_id"] / "image.png").read_bytes() == raw


def test_delete_confirmation_requires_actual_boolean_and_active_original_client(tmp_path):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Bound native confirmation.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, _ = _png_base64()
    chat_path = "/c/123e4567-e89b-12d3-a456-426614174000"
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                 cleanup_pending=True, chat_path=chat_path)
    queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")

    assert queue.status(submitted["job_id"])["chat_path"] == chat_path
    for value in (1, "true", False, None):
        with pytest.raises(ValueError, match="actual owner confirmation"):
            queue.confirm_delete(submitted["job_id"], value)
    with pytest.raises(ValueError, match="not paired"):
        queue.claim_delete_confirmation(str(uuid.uuid4()), submitted["job_id"])
    queue.client["seen"] -= 91
    with pytest.raises(ValueError, match="original paired extension must be online"):
        queue.confirm_delete(submitted["job_id"], True)


@pytest.mark.parametrize("cleanup_status", ["pending", "not_requested", "deleted", "failed"])
def test_delete_confirmation_rejects_wrong_cleanup_status(tmp_path, cleanup_status):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Wrong cleanup state.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, _ = _png_base64()
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                 cleanup_pending=cleanup_status != "not_requested",
                 chat_path="/c/123e4567-e89b-12d3-a456-426614174000")
    if cleanup_status in {"deleted", "failed"}:
        queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")
        if cleanup_status == "deleted":
            queue.confirm_delete(submitted["job_id"], True)
            queue.cleanup(CLIENT_ID, submitted["job_id"], "deleted")
        else:
            queue.cleanup(CLIENT_ID, submitted["job_id"], "failed", "synthetic")
    with pytest.raises(ValueError, match="saved-image chat"):
        queue.confirm_delete(submitted["job_id"], True)
    with pytest.raises(ValueError, match="only the original saved-image dialog"):
        queue.claim_delete_confirmation(CLIENT_ID, submitted["job_id"])


@pytest.mark.parametrize("blocked_state", ["pending", "confirmation_required"])
def test_cleanup_blocks_new_submit_and_pair_until_resolved(tmp_path, blocked_state):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Cleanup blocks replacement.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, _ = _png_base64()
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                 cleanup_pending=True, chat_path="/c/123e4567-e89b-12d3-a456-426614174000")
    if blocked_state == "confirmation_required":
        queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")
    with pytest.raises(ValueError, match="one image job at a time"):
        queue.submit("No concurrent job.", "Create image")
    with pytest.raises(ValueError, match="finish or resolve"):
        queue.pair(str(uuid.uuid4()), ACCOUNT)


@pytest.mark.parametrize("cleanup_status", ["pending", "confirmation_required"])
def test_restart_fails_unresolved_cleanup_and_invalidates_authorization(tmp_path, cleanup_status):
    root = tmp_path / "queue"
    queue = _paired_queue(root)
    submitted = queue.submit("Keep saved image across restart.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, raw = _png_base64()
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                 cleanup_pending=True, chat_path="/c/123e4567-e89b-12d3-a456-426614174000")
    if cleanup_status == "confirmation_required":
        queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")
        queue.confirm_delete(submitted["job_id"], True)

    restarted = ExtensionQueue(root / "extension-data", ACCOUNT)
    persisted = restarted.status(submitted["job_id"])
    assert persisted["state"] == "complete"
    assert persisted["cleanup_status"] == "failed"
    assert persisted["cleanup_confirmation"] == "invalidated"
    assert persisted["sha256"] == hashlib.sha256(raw).hexdigest()
    assert (root / "extension-data" / submitted["job_id"] / "image.png").read_bytes() == raw
    restarted.pair(CLIENT_ID, ACCOUNT)
    with pytest.raises(ValueError, match="saved-image chat"):
        restarted.confirm_delete(submitted["job_id"], True)


def test_cleanup_rejects_invalid_state_wrong_client_and_non_boolean_result_flag(tmp_path):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Do not accept malformed cleanup metadata.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, _ = _png_base64()

    with pytest.raises(ValueError, match="invalid cleanup flag"):
        queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64, cleanup_pending=1)
    assert queue.status(submitted["job_id"])["state"] == "claimed"
    complete = queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64, cleanup_pending=True)
    assert complete["cleanup_status"] == "pending"

    for invalid in ("pending", "not_requested", "archived", "", None):
        with pytest.raises(ValueError, match="invalid cleanup outcome"):
            queue.cleanup(CLIENT_ID, submitted["job_id"], invalid)
    with pytest.raises(ValueError, match="not paired"):
        queue.cleanup(str(uuid.uuid4()), submitted["job_id"], "deleted")
    assert queue.status(submitted["job_id"])["cleanup_status"] == "pending"


def test_cleanup_is_not_available_when_not_requested(tmp_path):
    queue = _paired_queue(tmp_path)
    job_id, _, complete = _complete_image_job(queue, cleanup_pending=False)

    assert complete["cleanup_status"] == "not_requested"
    with pytest.raises(ValueError, match="cleanup is not pending"):
        queue.cleanup(CLIENT_ID, job_id, "deleted")
    assert queue.status(job_id)["cleanup_status"] == "not_requested"


def test_http_cleanup_route_requires_confirmation_before_recording_delete(tmp_path):
    queue = _paired_queue(tmp_path)
    handler = make_handler(queue, TOKEN, 8767)
    job_id, raw, _ = _complete_image_job(queue)

    status, confirmation = _call_post(handler, "/cleanup", {
        "client_id": CLIENT_ID, "job_id": job_id, "cleanup_status": "confirmation_required",
    })
    assert status == 200
    assert confirmation["state"] == "complete"
    assert confirmation["cleanup_status"] == "confirmation_required"

    status, deleted = _call_post(handler, "/cleanup", {
        "client_id": CLIENT_ID, "job_id": job_id, "cleanup_status": "deleted",
    })
    assert status == 200
    assert deleted["state"] == "complete"
    assert deleted["cleanup_status"] == "deleted"
    assert deleted["sha256"] == hashlib.sha256(raw).hexdigest()

    status, _ = _call_post(handler, "/cleanup", {
        "client_id": CLIENT_ID, "job_id": job_id, "cleanup_status": "confirmation_required",
    })
    assert status == 400
    assert queue.status(job_id)["cleanup_status"] == "deleted"


def test_failed_result_is_terminal_and_error_is_bounded(tmp_path):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Make one image.", "Create image")
    queue.claim(CLIENT_ID)

    failed = queue.result(CLIENT_ID, submitted["job_id"], error="x" * 900)

    assert failed["state"] == "failed"
    assert len(failed["error"]) == 500
    assert queue.claim(CLIENT_ID) == {}


def test_invalid_or_oversized_image_payload_is_rejected_without_completing_job(tmp_path, monkeypatch):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Make one image.", "Create image")
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


def test_submit_enforces_prompt_exact_native_model_and_single_active_job_limits(tmp_path):
    queue = _paired_queue(tmp_path)

    for prompt in ("", "  ", "x" * 16001):
        with pytest.raises(ValueError, match="prompt"):
            queue.submit(prompt, "GPT-6 Pro")
    for model in ("", "  ", "x" * 101):
        with pytest.raises(ValueError, match="expected_model"):
            queue.submit("Draw one image.", model)
    for model in ("GPT-6 Pro", "Create image ", " create image"):
        with pytest.raises(ValueError, match="Create image"):
            queue.submit("Draw one image.", model)

    job = queue.submit("Draw one image.", "Create image")
    assert job["expected_model"] == "Create image"
    with pytest.raises(ValueError, match="one image job at a time"):
        queue.submit("A second image.", "Create image")


def test_stale_pairing_cannot_submit_when_extension_is_offline(tmp_path):
    queue = _paired_queue(tmp_path)
    queue.client["seen"] -= 91

    with pytest.raises(ValueError, match="heartbeat"):
        queue.submit("Do not dispatch while offline.", "Create image")


@pytest.mark.parametrize("terminal_state", ["interrupted", "failed"])
def test_terminal_history_does_not_block_explicit_new_job_or_replay_old_work(tmp_path, terminal_state):
    queue = _paired_queue(tmp_path)
    old = queue.submit("Prior uncertain image.", "Create image")
    queue.claim(CLIENT_ID)
    if terminal_state == "interrupted":
        queue.resolve(old["job_id"])
    else:
        queue.result(CLIENT_ID, old["job_id"], error="synthetic failure")

    new = queue.submit("Explicit new image.", "Create image")

    assert new["job_id"] != old["job_id"]
    assert queue.status(old["job_id"])["state"] == terminal_state
    claimed = queue.claim(CLIENT_ID)
    assert claimed["job_id"] == new["job_id"]
    assert claimed["prompt"] == "Explicit new image."
    assert queue.claim(CLIENT_ID) == {}


def test_resolve_marks_queued_work_interrupted_without_claiming_it(tmp_path):
    queue = _paired_queue(tmp_path)
    submitted = queue.submit("Uncertain upstream state.", "Create image")

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

    submitted = queue.submit("Render one image.", "Create image")
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


def test_http_cleanup_confirmation_claim_consumes_authorization_before_reply(tmp_path):
    queue = _paired_queue(tmp_path)
    handler = make_handler(queue, TOKEN, 8767)
    submitted = queue.submit("Native delete dialog.", "Create image")
    queue.claim(CLIENT_ID)
    image_base64, _ = _png_base64()
    queue.result(CLIENT_ID, submitted["job_id"], image_base64=image_base64,
                 cleanup_pending=True, chat_path="/c/123e4567-e89b-12d3-a456-426614174000")
    queue.cleanup(CLIENT_ID, submitted["job_id"], "confirmation_required")
    queue.confirm_delete(submitted["job_id"], True)

    status, result = _call_post(handler, "/cleanup-confirmation", {
        "client_id": CLIENT_ID, "job_id": submitted["job_id"],
    })
    assert status == 200 and result == {"confirmed": True}
    assert queue.status(submitted["job_id"])["cleanup_confirmation"] == "consumed"
    status, result = _call_post(handler, "/cleanup-confirmation", {
        "client_id": CLIENT_ID, "job_id": submitted["job_id"],
    })
    assert status == 200 and result == {"confirmed": False}
