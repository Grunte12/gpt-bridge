from chatgpt_api.providers.chatgpt.browser_onboarding import _capture_text


def test_browser_capture_text_uses_existing_neutral_capture_shape():
    text = _capture_text(
        "https://chatgpt.com/backend-api/f/conversation",
        {"authorization": "Bearer example", "content-type": "application/json"},
        '{"action":"next"}',
    )

    assert text.startswith("URL: https://chatgpt.com/backend-api/f/conversation\n")
    assert "authorization: Bearer example" in text
    assert text.endswith('Request Data: {"action":"next"}')
