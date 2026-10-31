import pytest
from chatgpt_api.cli import main
from chatgpt_api import extension_bridge as bridge


@pytest.mark.parametrize("arguments", [["setup"], ["auth", "login"], ["auth", "import"], ["mcp", "--account", "second"]])
def test_public_cli_rejects_capture_and_account_commands(arguments):
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_mcp_needs_no_account(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bridge, "main", lambda options: calls.append(options))
    assert main(["mcp", "--data-dir", str(tmp_path)]) == 0
    assert calls == [["--data-dir", str(tmp_path)]]


def test_missing_worker_has_extension_guidance(tmp_path, capsys):
    assert main(["status", "--data-dir", str(tmp_path), "--json"]) == 2
    assert "No cookies or account aliases" in capsys.readouterr().out


def test_account_free_pairing_and_heartbeat(tmp_path):
    queue = bridge.ExtensionQueue(tmp_path, "chrome")
    client = "11111111-1111-1111-1111-111111111111"
    assert queue.pair(client, visible_model="Create image", tab_id=7)["account_source"] == "chrome_login"
    queue.heartbeat(client, tab_ready=True, tab_id=7)
    assert queue.status()["extension_online"] is True


def test_reuses_live_worker_without_starting_another_queue(monkeypatch, tmp_path):
    token_file = tmp_path / "extension-token"
    token_file.write_text("x" * 40)
    token_file.chmod(0o600)
    calls = []
    monkeypatch.setattr(bridge.ExtensionClient, "status", lambda self: {"paired": True})
    monkeypatch.setattr(bridge, "main", lambda options: calls.append(options))
    assert main(["mcp", "--data-dir", str(tmp_path)]) == 0
    assert calls == [["--data-dir", str(tmp_path), "--connect"]]


def test_automatic_pair_is_atomic_across_profiles(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    queue = bridge.ExtensionQueue(tmp_path, "chrome")
    barrier = threading.Barrier(2)
    def pair(number):
        barrier.wait()
        try:
            queue.pair("11111111-1111-1111-1111-%012d" % number,
                       visible_model="Create image", tab_id=number, automatic=True)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(pair, [1, 2])) == [False, True]


def test_automatic_pair_preserves_queued_work(tmp_path):
    queue = bridge.ExtensionQueue(tmp_path, "chrome")
    client = "11111111-1111-1111-1111-111111111111"
    queue.pair(client, visible_model="Create image", input_protocol=4, tab_id=7)
    queue.submit("original work", "Create image")
    with pytest.raises(ValueError, match="existing work"):
        queue.pair(client, visible_model="Create image", tab_id=8, automatic=True)
    assert queue.client["tab_id"] == 7
