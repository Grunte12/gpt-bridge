import json
import threading
import urllib.error
import urllib.request

import pytest

from chatgpt_api.providers.chatgpt.local_setup import capture_from_local_setup_page


CAPTURE_TEXT = """
curl 'https://chatgpt.com/backend-api/f/conversation' \\
  -H 'Authorization: Bearer fake-token' \\
  -H 'Cookie: oai-did=device-1; __Secure-next-auth.session-token.0=session-1' \\
  --data-raw '{"action":"next","model":"gpt-5-6-thinking"}'
""".strip()


def _post_capture(setup_url: str, capture_text: str) -> tuple[int, dict[str, object]]:
    token = setup_url.rsplit("/", 1)[-1]
    submit_url = setup_url.replace(f"/setup/{token}", f"/submit/{token}")
    body = json.dumps({"capture_text": capture_text}).encode("utf-8")
    request = urllib.request.Request(
        submit_url,
        data=body,
        headers={"Content-Type": "application/json", "Origin": setup_url.rsplit("/setup/", 1)[0]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_local_setup_accepts_one_capture_and_exits_without_daemon():
    response: list[tuple[int, dict[str, object]]] = []
    threads: list[threading.Thread] = []

    def opener(url: str) -> bool:
        thread = threading.Thread(
            target=lambda: response.append(_post_capture(url, CAPTURE_TEXT)),
            daemon=True,
        )
        threads.append(thread)
        thread.start()
        return True

    result = capture_from_local_setup_page(timeout_seconds=5, opener=opener)
    threads[0].join(timeout=5)

    assert result.capture_text == CAPTURE_TEXT
    assert response == [(200, {"ok": True, "message": "Capture received locally. You may close this tab and return to the terminal."})]


def test_local_setup_rejects_non_chatgpt_capture_then_accepts_valid_capture():
    responses: list[tuple[int, dict[str, object]]] = []
    threads: list[threading.Thread] = []

    def opener(url: str) -> bool:
        def submit() -> None:
            responses.append(
                _post_capture(
                    url,
                    CAPTURE_TEXT.replace("https://chatgpt.com", "https://example.com"),
                )
            )
            responses.append(_post_capture(url, CAPTURE_TEXT))

        thread = threading.Thread(target=submit, daemon=True)
        threads.append(thread)
        thread.start()
        return True

    result = capture_from_local_setup_page(timeout_seconds=5, opener=opener)
    threads[0].join(timeout=5)

    assert result.capture_text == CAPTURE_TEXT
    assert responses[0][0] == 400
    assert responses[0][1]["ok"] is False
    assert responses[1][0] == 200


def test_local_setup_uses_random_tokenized_loopback_url():
    announced: list[str] = []

    def opener(url: str) -> bool:
        threading.Thread(target=lambda: _post_capture(url, CAPTURE_TEXT), daemon=True).start()
        return True

    capture_from_local_setup_page(timeout_seconds=5, opener=opener, announce=announced.append)

    assert announced[0].startswith("Local setup page: http://127.0.0.1:")
    assert "/setup/" in announced[0]
    assert len(announced[0].rsplit("/", 1)[-1]) >= 32
