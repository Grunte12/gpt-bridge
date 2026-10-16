"""Offline tests for local reference images in the native extension queue."""

import base64
import hashlib
import io
import json
import os
import stat
import struct
import zlib

import pytest
from PIL import Image

from chatgpt_api.extension_bridge import (
    ExtensionClient,
    ExtensionQueue,
    LocalImageInput,
    create_mcp,
    make_handler,
)


ACCOUNT = "second"
CLIENT_ID = "123e4567-e89b-12d3-a456-426614174000"


def _paired_queue(root):
    queue = ExtensionQueue(root, ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=1)
    return queue


def _write_image(path, *, size=(8, 6), color=(30, 90, 150), fmt="PNG"):
    image = Image.new("RGB", size, color)
    image.save(path, format=fmt)
    return path.read_bytes()


def _input(path, description, role="reference"):
    return {"path": str(path), "role": role, "description": description}


def test_protocol_zero_disables_reference_create_and_source_edit_inputs(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=0)
    prompt_only = queue.submit("Create without local files.", "Create image")
    assert prompt_only["mode"] == "create"
    assert prompt_only.get("images", []) == []
    queue.claim(CLIENT_ID)
    queue.result(CLIENT_ID, prompt_only["job_id"], error="finish synthetic prompt-only job")
    path = tmp_path / "input.png"
    _write_image(path)

    assert queue.status()["input_capabilities"]["ordered_local_images"] is False
    assert queue.status()["input_capabilities"]["preflight_only"] is False
    with pytest.raises(ValueError, match="reload the updated extension"):
        queue.submit("Create with a reference.", "Create image", images=[
            _input(path, "reference"),
        ])
    with pytest.raises(ValueError, match="reload the updated extension"):
        queue.submit("Edit from a source.", "Create image", mode="edit", images=[
            _input(path, "source", "source"),
        ])
    assert len(queue.jobs) == 1
    assert next(iter(queue.jobs.values()))["state"] == "failed"


def test_protocol_one_heartbeat_enables_local_image_capability(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=0)

    status = queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=1)

    assert status["tab_ready"] is True
    assert status["input_capabilities"]["ordered_local_images"] is True
    assert status["input_capabilities"]["preflight_only"] is False


def test_protocol_downgrade_fails_queued_input_before_exposing_snapshot_bytes(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    path = tmp_path / "reference.png"
    _write_image(path)
    submitted = queue.submit("Use this reference.", "Create image", images=[
        _input(path, "visual reference"),
    ])
    queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=0)

    with pytest.raises(ValueError, match="Input protocol changed before delivery; nothing was delivered"):
        queue.claim(CLIENT_ID)

    status = queue.status(submitted["job_id"])
    assert status["state"] == "failed"
    assert "data_base64" not in json.dumps(status)
    assert queue.claim(CLIENT_ID) == {}


def test_protocol_one_rejects_preflight_while_protocol_two_enables_it(tmp_path):
    path = tmp_path / "reference.png"
    _write_image(path)
    old = ExtensionQueue(tmp_path / "protocol-one", ACCOUNT)
    old.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=1)
    assert old.status()["input_capabilities"]["preflight_only"] is False
    with pytest.raises(ValueError, match="no-Send preflight support"):
        old.submit("Check without sending.", "Create image", images=[
            _input(path, "visual reference"),
        ], preflight_only=True)
    assert old.jobs == {}

    current = ExtensionQueue(tmp_path / "protocol-two", ACCOUNT)
    current.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)
    assert current.status()["input_capabilities"]["preflight_only"] is True
    submitted = current.submit("Check without sending.", "Create image", images=[
        _input(path, "visual reference"),
    ], preflight_only=True)
    assert submitted["preflight_only"] is True


def test_protocol_three_enables_upload_clear_capability_and_accepts_heartbeat(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=3)

    assert queue.status()["input_capabilities"]["preflight_only"] is True
    assert queue.status()["input_capabilities"]["preflight_clear_uploads"] is True
    status = queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=3)
    assert status["input_capabilities"]["preflight_clear_uploads"] is True


def test_clear_preflight_uploads_requires_protocol_three_and_preflight_before_writing(tmp_path):
    path = tmp_path / "reference.png"
    raw = _write_image(path)
    old = ExtensionQueue(tmp_path / "protocol-two", ACCOUNT)
    old.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)

    with pytest.raises(ValueError, match="protocol 3 is required"):
        old.submit(
            "Clear only after preflight readiness.",
            "Create image",
            images=[_input(path, "visual reference")],
            preflight_only=True,
            clear_preflight_uploads=True,
        )
    assert old.jobs == {}
    assert list(old.root.iterdir()) == []
    assert path.read_bytes() == raw

    current = ExtensionQueue(tmp_path / "protocol-three", ACCOUNT)
    current.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=3)
    with pytest.raises(ValueError, match="preflight_only=true"):
        current.submit("Clear is not generation cleanup.", "Create image", clear_preflight_uploads=True)
    for invalid in (0, 1, "true", None):
        with pytest.raises(ValueError, match="clear_preflight_uploads requires a boolean"):
            current.submit(
                "Strict clear flag.",
                "Create image",
                preflight_only=True,
                clear_preflight_uploads=invalid,
            )
    assert current.jobs == {}
    assert list(current.root.iterdir()) == []


def test_preflight_only_flag_requires_a_real_boolean(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)
    for invalid in (0, 1, "true", None):
        with pytest.raises(ValueError, match="preflight_only must be a boolean"):
            queue.submit("Strict flag only.", "Create image", preflight_only=invalid)
    assert queue.jobs == {}


def test_clear_preflight_claim_preserves_order_and_is_only_marked_when_opted_in(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT, auto_delete_saved_chats=True)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=3)
    paths = [tmp_path / f"clear-ref-{index}.png" for index in range(5)]
    [_write_image(path, color=(index * 20, 40, 90)) for index, path in enumerate(paths)]

    submitted = queue.submit(
        "Upload references without sending.",
        "Create image",
        images=[_input(path, f"reference {index}") for index, path in enumerate(paths, 1)],
        preflight_only=True,
        clear_preflight_uploads=True,
    )
    assert submitted["clear_preflight_uploads"] is True
    assert queue.jobs[submitted["job_id"]].get("auto_delete_saved_chat") is None

    claimed = queue.claim(CLIENT_ID)
    assert claimed["clear_preflight_uploads"] is True
    assert [image["order"] for image in claimed["images"]] == [1, 2, 3, 4, 5]
    assert [image["role"] for image in claimed["images"]] == ["reference"] * 5


def test_clear_preflight_downgrade_to_protocol_two_fails_before_delivery(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=3)
    path = tmp_path / "reference.png"
    _write_image(path)
    submitted = queue.submit(
        "Do not deliver after protocol downgrade.",
        "Create image",
        images=[_input(path, "visual reference")],
        preflight_only=True,
        clear_preflight_uploads=True,
    )
    queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=2)

    assert queue.status()["input_capabilities"]["preflight_clear_uploads"] is False
    with pytest.raises(ValueError, match="Input protocol changed before delivery; nothing was delivered"):
        queue.claim(CLIENT_ID)
    status = queue.status(submitted["job_id"])
    assert status["state"] == "failed"
    assert "data_base64" not in json.dumps(status)
    assert queue.claim(CLIENT_ID) == {}


def test_preflight_downgrade_to_protocol_one_fails_before_delivery(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)
    path = tmp_path / "reference.png"
    _write_image(path)
    submitted = queue.submit("Do not send this test draft.", "Create image", images=[
        _input(path, "visual reference"),
    ], preflight_only=True)
    queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=1)

    assert queue.status()["input_capabilities"]["ordered_local_images"] is True
    assert queue.status()["input_capabilities"]["preflight_only"] is False
    with pytest.raises(ValueError, match="Input protocol changed before delivery; nothing was delivered"):
        queue.claim(CLIENT_ID)
    status = queue.status(submitted["job_id"])
    assert status["state"] == "failed"
    assert "data_base64" not in json.dumps(status)
    assert queue.claim(CLIENT_ID) == {}


def test_preflight_receipt_completes_without_image_or_cleanup_authorization(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT, auto_delete_saved_chats=True)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)
    paths = [tmp_path / "first.png", tmp_path / "second.webp"]
    [_write_image(paths[0]), _write_image(paths[1], fmt="WEBP")]
    submitted = queue.submit("Keep this ordered draft unsent.", "Create image", images=[
        _input(paths[0], "first reference"), _input(paths[1], "second reference"),
    ], preflight_only=True)
    assert "auto_delete_saved_chat" not in queue.jobs[submitted["job_id"]]

    claimed = queue.claim(CLIENT_ID)
    assert claimed["preflight_only"] is True
    assert [image["order"] for image in claimed["images"]] == [1, 2]
    result = queue.result(CLIENT_ID, submitted["job_id"], preflight_ready=True)

    assert result["state"] == "complete"
    assert result["preflight_ready"] is True
    assert result["submitted"] is False
    assert result["generated"] is False
    assert result["cleanup_status"] == "not_requested"
    assert result["draft_note"] == "Owned upload-only draft remains unsent; inspect before further work."
    assert "preflight_uploads_cleared" not in result
    assert "image_path" not in result
    assert not list((queue.root / submitted["job_id"]).glob("image.*"))


@pytest.mark.parametrize("invalid", [0, 1, "true", None])
def test_clear_preflight_requires_strict_matching_clear_receipt(tmp_path, invalid):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT, auto_delete_saved_chats=True)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=3)
    path = tmp_path / "reference.png"
    raw = _write_image(path)
    submitted = queue.submit(
        "Upload and clear only the verified reference.",
        "Create image",
        images=[_input(path, "visual reference")],
        preflight_only=True,
        clear_preflight_uploads=True,
    )
    claimed = queue.claim(CLIENT_ID)
    assert claimed["clear_preflight_uploads"] is True

    with pytest.raises(ValueError, match="invalid cleanup flag"):
        queue.result(
            CLIENT_ID,
            submitted["job_id"],
            preflight_ready=True,
            preflight_uploads_cleared=invalid,
        )
    with pytest.raises(ValueError, match="verified preflight upload clearing receipt is required"):
        queue.result(CLIENT_ID, submitted["job_id"], preflight_ready=True)
    assert queue.status(submitted["job_id"])["state"] == "claimed"

    receipt = queue.result(
        CLIENT_ID,
        submitted["job_id"],
        preflight_ready=True,
        preflight_uploads_cleared=True,
    )
    assert receipt["state"] == "complete"
    assert receipt["preflight_ready"] is True
    assert receipt["preflight_uploads_cleared"] is True
    assert receipt["submitted"] is False
    assert receipt["generated"] is False
    assert receipt["cleanup_status"] == "not_requested"
    assert receipt["draft_note"] == "Owned preflight uploads removed after readiness verification; composer empty."
    assert "image_path" not in receipt
    assert "chat_path" not in receipt
    assert "auto_delete_saved_chat" not in queue.jobs[submitted["job_id"]]
    assert not list((queue.root / submitted["job_id"]).glob("image.*"))
    assert (queue.root / submitted["job_id"] / submitted["images"][0]["name"]).read_bytes() == raw


@pytest.mark.parametrize("preflight_only", [False, True])
def test_clear_receipt_is_rejected_without_clear_opt_in(tmp_path, preflight_only):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=3)
    submitted = queue.submit(
        "Only opted-in jobs can clear uploads.", "Create image", preflight_only=preflight_only,
    )
    queue.claim(CLIENT_ID)

    with pytest.raises(ValueError, match="preflight upload clearing was not requested"):
        queue.result(
            CLIENT_ID,
            submitted["job_id"],
            preflight_ready=preflight_only,
            preflight_uploads_cleared=True,
        )
    assert queue.status(submitted["job_id"])["state"] == "claimed"


@pytest.mark.parametrize("receipt", [
    {},
    {"preflight_ready": True, "image_base64": "eA=="},
    {"preflight_ready": True, "cleanup_pending": True},
    {"preflight_ready": True, "chat_path": "/c/123e4567-e89b-12d3-a456-426614174000"},
])
def test_preflight_rejects_missing_or_media_cleanup_receipts(tmp_path, receipt):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)
    submitted = queue.submit("Only readiness is allowed.", "Create image", preflight_only=True)
    queue.claim(CLIENT_ID)

    with pytest.raises(ValueError, match="preflight accepts only a no-Send readiness receipt"):
        queue.result(CLIENT_ID, submitted["job_id"], **receipt)
    assert queue.status(submitted["job_id"])["state"] == "claimed"


def test_generation_rejects_preflight_readiness_receipt(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    submitted = queue.submit("Generate normally.", "Create image")
    queue.claim(CLIENT_ID)

    with pytest.raises(ValueError, match="readiness receipt cannot complete a generation job"):
        queue.result(CLIENT_ID, submitted["job_id"], preflight_ready=True)
    assert queue.status(submitted["job_id"])["state"] == "claimed"


def test_heartbeat_exposes_and_validates_tab_diagnostics(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)

    status = queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=2,
                             tab_idle=False, tab_error="Composer has an unrelated draft")

    assert status["tab_idle"] is False
    assert status["tab_error"] == "Composer has an unrelated draft"
    for invalid in (
        {"tab_idle": 1},
        {"tab_error": 123},
        {"tab_error": "x" * 301},
    ):
        with pytest.raises(ValueError, match="invalid tab diagnostic"):
            queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=2, **invalid)


@pytest.mark.parametrize("protocol", [True, 5])
def test_pair_rejects_boolean_and_unsupported_input_protocols(tmp_path, protocol):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)

    with pytest.raises(ValueError, match="invalid input protocol"):
        queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=protocol)
    assert queue.client is None


@pytest.mark.parametrize("protocol", [True, 5])
def test_heartbeat_rejects_boolean_and_unsupported_input_protocols(tmp_path, protocol):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=1)

    with pytest.raises(ValueError, match="invalid input protocol"):
        queue.heartbeat(CLIENT_ID, ACCOUNT, tab_ready=True, input_protocol=protocol)
    assert queue.status()["input_capabilities"]["ordered_local_images"] is True


def test_create_accepts_zero_or_multiple_ordered_references_and_compact_status(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    empty = queue.submit("Create without images.", "Create image")
    assert empty["mode"] == "create"
    assert empty.get("images", []) == []
    queue.claim(CLIENT_ID)
    queue.result(CLIENT_ID, empty["job_id"], error="finish synthetic no-reference job")

    paths = [tmp_path / f"ref-{index}.png" for index in range(3)]
    source_bytes = [_write_image(path, color=(index * 40, 20, 80)) for index, path in enumerate(paths)]
    descriptions = ["character identity", "wardrobe", "lighting"]
    submitted = queue.submit("Use three visual references.", "Create image", images=[
        _input(path, descriptions[index]) for index, path in enumerate(paths)
    ])

    metadata = submitted["images"]
    assert [item["order"] for item in metadata] == [1, 2, 3]
    assert [item["role"] for item in metadata] == ["reference"] * 3
    assert [item["description"] for item in metadata] == descriptions
    assert [item["name"] for item in metadata] == [
        f"input-{index:03d}-{submitted['job_id']}.png" for index in range(1, 4)
    ]
    assert all({"bytes", "sha256", "mime", "dimensions"} <= item.keys() for item in metadata)
    assert all("path" not in item and "data_base64" not in item for item in metadata)
    assert all(str(path) not in repr(submitted) for path in paths)
    for item, raw in zip(metadata, source_bytes):
        snapshot = queue.root / submitted["job_id"] / item["name"]
        assert snapshot.read_bytes() == raw
        assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    assert stat.S_IMODE((queue.root / submitted["job_id"]).stat().st_mode) == 0o700


def test_queue_snapshot_names_are_unique_per_job_and_preserve_digest_bytes(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    source = tmp_path / "same-source.png"

    first_raw = _write_image(source, color=(190, 30, 40))
    first = queue.submit("Use the first source snapshot.", "Create image", images=[
        _input(source, "visual reference"),
    ])
    first_image = first["images"][0]
    assert first_image["name"] == f"input-001-{first['job_id']}.png"
    assert first_image["sha256"] == hashlib.sha256(first_raw).hexdigest()
    assert (queue.root / first["job_id"] / first_image["name"]).read_bytes() == first_raw
    first_claim = queue.claim(CLIENT_ID)
    assert base64.b64decode(first_claim["images"][0]["data_base64"]) == first_raw
    assert first_claim["images"][0]["sha256"] == first_image["sha256"]
    queue.result(CLIENT_ID, first["job_id"], error="finish the first snapshot test job")

    second_raw = _write_image(source, color=(20, 160, 70))
    second = queue.submit("Use the second source snapshot.", "Create image", images=[
        _input(source, "visual reference"),
    ])
    second_image = second["images"][0]
    assert second_image["name"] == f"input-001-{second['job_id']}.png"
    assert second_image["name"] != first_image["name"]
    assert second_image["sha256"] == hashlib.sha256(second_raw).hexdigest()
    assert (queue.root / second["job_id"] / second_image["name"]).read_bytes() == second_raw
    second_claim = queue.claim(CLIENT_ID)
    assert base64.b64decode(second_claim["images"][0]["data_base64"]) == second_raw
    assert second_claim["images"][0]["sha256"] == second_image["sha256"]


def test_edit_requires_source_and_create_rejects_source_role(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    path = tmp_path / "source.png"
    _write_image(path)

    with pytest.raises(ValueError, match="at least one source"):
        queue.submit("Edit this source.", "Create image", mode="edit")
    with pytest.raises(ValueError, match="source images require edit"):
        queue.submit("Create with a source role.", "Create image",
                     images=[_input(path, "product source", "source")])

    submitted = queue.submit("Change only the background.", "Create image", mode="edit", images=[
        _input(path, "preserve product geometry", "source"),
        _input(path, "use as lighting reference"),
    ])
    assert submitted["mode"] == "edit"
    assert [(item["order"], item["role"]) for item in submitted["images"]] == [
        (1, "source"), (2, "reference"),
    ]


def test_claim_reads_immutable_snapshots_once_and_restart_never_replays(tmp_path):
    root = tmp_path / "queue"
    queue = _paired_queue(root)
    originals = [tmp_path / "first.png", tmp_path / "second.webp"]
    raw = [
        _write_image(originals[0], color=(200, 10, 20)),
        _write_image(originals[1], color=(5, 190, 40), fmt="WEBP"),
    ]
    submitted = queue.submit("Use these in order.", "Create image", images=[
        _input(originals[0], "source photo", "source"),
        _input(originals[1], "style reference"),
    ], mode="edit")

    _write_image(originals[0], color=(0, 0, 0))
    (queue.root / submitted["job_id"] / submitted["images"][1]["name"]).write_bytes(raw[1] + b"tampered")
    # Claim rejects a changed private snapshot before delivering any part of the job.
    with pytest.raises(ValueError, match="snapshot unavailable or changed"):
        queue.claim(CLIENT_ID)
    assert queue.status(submitted["job_id"])["state"] == "failed"
    assert queue.claim(CLIENT_ID) == {}


def test_claim_returns_snapshot_bytes_then_consumes_job_and_restart_does_not_replay(tmp_path):
    root = tmp_path / "queue"
    queue = _paired_queue(root)
    path = tmp_path / "source.png"
    raw = _write_image(path, color=(120, 50, 210))
    submitted = queue.submit("One exact upload.", "Create image", mode="edit", images=[
        _input(path, "edit source", "source"),
    ])
    _write_image(path, color=(0, 0, 0))

    claimed = queue.claim(CLIENT_ID)
    assert claimed["job_id"] == submitted["job_id"]
    assert claimed["mode"] == "edit"
    image = claimed["images"][0]
    assert image["role"] == "source" and image["order"] == 1
    assert base64.b64decode(image["data_base64"]) == raw
    assert image["sha256"] == submitted["images"][0]["sha256"]
    assert "path" not in image
    assert queue.claim(CLIENT_ID) == {}

    restarted = ExtensionQueue(root, ACCOUNT)
    assert restarted.status(submitted["job_id"])["state"] == "interrupted"
    restarted.pair(CLIENT_ID, ACCOUNT, input_protocol=1)
    assert restarted.claim(CLIENT_ID) == {}


@pytest.mark.parametrize("bad_reference", [
    "https://example.com/image.png",
    "data:image/png;base64,aGVsbG8=",
    "bm90LWE=",
])
def test_inputs_reject_urls_and_inline_payloads(tmp_path, bad_reference):
    queue = _paired_queue(tmp_path / "queue")
    with pytest.raises(ValueError, match="absolute and local"):
        queue.submit("No remote or inline images.", "Create image",
                     images=[_input(bad_reference, "untrusted image")])


def test_inputs_reject_symlink_components_and_non_regular_files(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    real = tmp_path / "real.png"
    _write_image(real)
    link = tmp_path / "linked.png"
    link.symlink_to(real)
    linked_dir = tmp_path / "linked-dir"
    linked_dir.symlink_to(tmp_path, target_is_directory=True)
    fifo = tmp_path / "image.fifo"
    os.mkfifo(fifo)

    for path in (link, linked_dir / real.name, fifo):
        with pytest.raises((ValueError, OSError)):
            queue.submit("Reject unsafe path.", "Create image",
                         images=[_input(path, "unsafe")])
    assert queue.jobs == {}


@pytest.mark.parametrize("fmt", ["GIF", "BMP"])
def test_inputs_reject_unsupported_formats_and_oversized_edge(tmp_path, fmt):
    queue = _paired_queue(tmp_path / "queue")
    unsupported = tmp_path / f"unsupported.{fmt.lower()}"
    _write_image(unsupported, fmt=fmt)
    with pytest.raises(ValueError, match="unsupported input image"):
        queue.submit("Unsupported input.", "Create image", images=[_input(unsupported, "bad format")])

    too_wide = tmp_path / "too-wide.png"
    _write_image(too_wide, size=(8193, 1))
    with pytest.raises(ValueError, match="unsupported input image"):
        queue.submit("Edge exceeds the limit.", "Create image", images=[_input(too_wide, "oversized edge")])


def test_input_images_respect_per_file_and_combined_transport_budget(tmp_path, monkeypatch):
    import chatgpt_api.extension_bridge as bridge

    queue = _paired_queue(tmp_path / "queue")
    one = tmp_path / "one.png"
    two = tmp_path / "two.png"
    base = _write_image(one)
    two.write_bytes(base + b"x" * 150)
    one.write_bytes(base + b"y" * 150)
    monkeypatch.setattr(bridge, "MAX_INPUT_BYTES", 300)
    with pytest.raises(ValueError, match="combined inputs"):
        queue.submit("Combined refs exceed budget.", "Create image", images=[
            _input(one, "first"), _input(two, "second"),
        ])

    oversized = tmp_path / "oversized.png"
    oversized.write_bytes(base + b"z" * 250)
    with pytest.raises(ValueError, match="regular image within the 8 MiB"):
        queue.submit("One ref exceeds budget.", "Create image", images=[_input(oversized, "large")])
    assert queue.jobs == {}


def test_mcp_image_schema_exposes_mode_and_typed_local_image_inputs():
    server = create_mcp(None)
    tool = next(tool for tool in server._tool_manager.list_tools() if tool.name == "extension_image")
    schema = tool.parameters
    assert schema["properties"]["mode"]["enum"] == ["create", "edit"]
    assert schema["properties"]["mode"]["default"] == "create"
    image_schema = schema["$defs"]["LocalImageInput"]
    assert image_schema["additionalProperties"] is False
    assert image_schema["properties"]["role"]["enum"] == ["source", "reference"]
    assert image_schema["properties"]["description"]["maxLength"] == 200
    assert image_schema["required"] == ["path", "description"]
    assert "images" not in schema.get("required", [])
    assert schema["properties"]["preflight_only"]["type"] == "boolean"
    assert schema["properties"]["preflight_only"]["default"] is False
    assert "preflight_only" not in schema.get("required", [])
    assert schema["properties"]["clear_preflight_uploads"]["type"] == "boolean"
    assert schema["properties"]["clear_preflight_uploads"]["default"] is False
    assert "clear_preflight_uploads" not in schema.get("required", [])


@pytest.mark.parametrize(("fmt", "suffix", "mime"), [
    ("JPEG", "jpg", "image/jpeg"),
    ("WEBP", "webp", "image/webp"),
])
def test_valid_jpeg_and_static_webp_are_accepted(tmp_path, fmt, suffix, mime):
    queue = _paired_queue(tmp_path / "queue")
    path = tmp_path / f"reference.{suffix}"
    _write_image(path, size=(9, 7), fmt=fmt)

    submitted = queue.submit("Use this reference.", "Create image", images=[
        _input(path, "visual reference"),
    ])

    assert submitted["images"][0]["name"] == f"input-001-{submitted['job_id']}.{suffix}"
    assert submitted["images"][0]["mime"] == mime
    assert submitted["images"][0]["dimensions"] == [9, 7]


def test_corrupt_image_is_rejected_without_creating_a_job(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image")

    with pytest.raises(ValueError, match="not a valid static PNG, JPEG or WebP"):
        queue.submit("Reject corrupt input.", "Create image", images=[
            _input(corrupt, "corrupt reference"),
        ])
    assert queue.jobs == {}


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_animated_png_and_webp_are_rejected(tmp_path, fmt):
    queue = _paired_queue(tmp_path / "queue")
    path = tmp_path / f"animated.{fmt.lower()}"
    first = Image.new("RGB", (4, 4), (20, 40, 60))
    second = Image.new("RGB", (4, 4), (60, 40, 20))
    first.save(path, format=fmt, save_all=True, append_images=[second], duration=100, loop=0)

    with pytest.raises(ValueError, match="unsupported input image"):
        queue.submit("Reject animation.", "Create image", images=[
            _input(path, "animated reference"),
        ])
    assert queue.jobs == {}


def test_description_schema_unknown_fields_and_relative_paths_are_rejected(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    valid = tmp_path / "valid.png"
    _write_image(valid)

    for description in ("   ", "line one\nline two", "x" * 201):
        with pytest.raises(ValueError):
            queue.submit("Reject invalid descriptions.", "Create image", images=[
                _input(valid, description),
            ])
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        queue.submit("Reject unknown fields.", "Create image", images=[
            {**_input(valid, "reference"), "unexpected": "value"},
        ])
    with pytest.raises(ValueError, match="absolute and local"):
        queue.submit("Reject relative paths.", "Create image", images=[
            _input("relative.png", "reference"),
        ])
    assert queue.jobs == {}


def test_image_pixel_bound_rejects_over_40mp_without_decoding_pixels(tmp_path):
    # A valid PNG header advertises dimensions over the limit; the validator
    # must reject on metadata before trying to decode a large pixel buffer.
    width = height = 8192
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_chunk = b"IHDR" + ihdr
    header += struct.pack(">I", len(ihdr)) + ihdr_chunk
    header += struct.pack(">I", zlib.crc32(ihdr_chunk) & 0xffffffff)
    idat = b"IDAT"
    header += struct.pack(">I", 0) + idat + struct.pack(">I", zlib.crc32(idat) & 0xffffffff)
    oversized = tmp_path / "over-40mp.png"
    oversized.write_bytes(header)
    queue = _paired_queue(tmp_path / "queue")

    with pytest.raises(ValueError, match="unsupported input image"):
        queue.submit("Reject over 40 MP.", "Create image", images=[
            _input(oversized, "oversized reference"),
        ])
    assert queue.jobs == {}


def test_metadata_budget_is_48kib_and_rejects_without_a_job(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    path = tmp_path / "small.png"
    _write_image(path, size=(1, 1))
    many_descriptions = [
        _input(path, f"{index:03d} " + "x" * 190)
        for index in range(130)
    ]

    with pytest.raises(ValueError, match="48 KiB Bridge state budget"):
        queue.submit("Reject oversized metadata.", "Create image", images=many_descriptions)
    assert queue.jobs == {}


def test_extension_client_serializes_local_image_input_to_local_worker_payload(tmp_path):
    queue = ExtensionQueue(tmp_path / "queue", ACCOUNT)
    queue.pair(CLIENT_ID, ACCOUNT, "Create image", input_protocol=2)
    handler_type = make_handler(queue, "synthetic-token", 18767)
    captured_payloads = []

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return self.body

    class LocalWorkerTransport:
        def open(self, request, timeout):
            assert timeout == 10
            body = request.data
            captured_payloads.append(json.loads(body))
            handler = object.__new__(handler_type)
            handler.headers = {
                "Host": "127.0.0.1:18767",
                "Origin": "",
                "Authorization": request.get_header("Authorization"),
                "Content-Length": str(len(body)),
            }
            handler.path = "/agent/image"
            handler.rfile = io.BytesIO(body)
            handler.wfile = io.BytesIO()
            handler.send_response = lambda code: setattr(handler, "status", code)
            handler.send_header = lambda *_args: None
            handler.end_headers = lambda: None
            handler.do_POST()
            assert handler.status == 200
            return Response(handler.wfile.getvalue())

    path = tmp_path / "client-input.webp"
    raw = _write_image(path, size=(7, 5), fmt="WEBP")
    image_input = LocalImageInput(path=str(path), role="reference", description="match color")
    client = ExtensionClient("synthetic-token")
    client.http = LocalWorkerTransport()

    submitted = client.submit("Use this exact reference.", "Create image", images=[image_input],
                              preflight_only=True)

    assert captured_payloads == [{
        "prompt": "Use this exact reference.",
        "expected_model": "Create image",
        "mode": "create",
        "images": [image_input.model_dump()],
        "preflight_only": True,
    }]
    assert submitted["preflight_only"] is True
    assert submitted["images"][0]["mime"] == "image/webp"
    assert submitted["images"][0]["bytes"] == len(raw)


def test_paths_and_base64_are_absent_from_persisted_state_and_public_status(tmp_path):
    queue = _paired_queue(tmp_path / "queue")
    path = tmp_path / "private-reference.png"
    _write_image(path)

    submitted = queue.submit("Keep local path private.", "Create image", images=[
        _input(path, "private reference"),
    ])
    state_text = (queue.root / submitted["job_id"] / "state.json").read_text()
    job_status = queue.status(submitted["job_id"])
    overview_status = queue.status()

    assert str(path) not in state_text
    assert "data_base64" not in state_text
    for status in (submitted, job_status, overview_status):
        serialized = json.dumps(status)
        assert str(path) not in serialized
        assert "data_base64" not in serialized
    assert "images" not in overview_status["jobs"][0]
