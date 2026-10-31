import io
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from chatgpt_api import native_pairing as native

ID = "a" * 32


def test_native_install_is_restricted_and_does_not_copy_secret(tmp_path):
    manifest = native.install(ID, tmp_path / "data", home=tmp_path)
    value = json.loads(manifest.read_text())
    assert value["allowed_origins"] == ["chrome-extension://" + ID + "/"]
    assert Path(value["path"]).is_file()
    assert "token" not in manifest.read_text()
    with pytest.raises(ValueError):
        native.install("*", tmp_path / "data", home=tmp_path)


def test_native_bootstrap_checks_origin_action_and_permissions(tmp_path):
    token = tmp_path / "extension-token"
    token.write_text("x" * 40)
    token.chmod(0o600)
    config = {"data_dir": str(tmp_path), "origin": "chrome-extension://" + ID + "/"}
    assert native.respond(config, config["origin"], {"action": "pair"}) == {"token": "x" * 40}
    for origin, request in [("https://evil.test", {"action": "pair"}), (config["origin"], {"action": "read", "path": "/etc/passwd"})]:
        with pytest.raises(ValueError):
            native.respond(config, origin, request)
    token.chmod(0o644)
    with pytest.raises(ValueError):
        native.respond(config, config["origin"], {"action": "pair"})


def test_native_host_actual_stdio_protocol(tmp_path):
    manifest = json.loads(native.install(ID, tmp_path / "data with spaces", home=tmp_path).read_text())
    token = tmp_path / "data with spaces/extension-token"
    token.write_text("x" * 40)
    token.chmod(0o600)
    payload = json.dumps({"action": "pair"}).encode()
    process = subprocess.run([manifest["path"], manifest["allowed_origins"][0]],
                             input=struct.pack("=I", len(payload)) + payload, capture_output=True)
    assert process.returncode == 0, process.stderr.decode()
    assert struct.unpack("=I", process.stdout[:4])[0] == len(process.stdout[4:])
    assert json.loads(process.stdout[4:]) == {"token": "x" * 40}


@pytest.mark.parametrize("message", [[], None, {"action": "pair", "extra": True}])
def test_native_host_rejects_malformed_messages_without_leaking_secret(tmp_path, message):
    manifest = json.loads(native.install(ID, tmp_path / "data", home=tmp_path).read_text())
    token = tmp_path / "data/extension-token"
    token.write_text("secret-value-that-must-not-leak" * 2)
    token.chmod(0o600)
    payload = json.dumps(message).encode()
    process = subprocess.run([manifest["path"], manifest["allowed_origins"][0]],
                             input=struct.pack("=I", len(payload)) + payload, capture_output=True)
    assert json.loads(process.stdout[4:]).get("error")
    assert b"secret-value" not in process.stdout + process.stderr
