import json

import pytest

from chatgpt_api.web_sessions import (
    compact_branch,
    compact_conversation_list,
    conversation_id_from_reference,
    conversation_markdown,
    current_branch_assets,
    current_branch_messages,
    normalized_conversation,
    write_conversation,
)


CONVERSATION_ID = "12345678-abcd-4321-abcd-1234567890ab"


def _conversation():
    return {
        "id": CONVERSATION_ID,
        "title": "Adaptive agent brainstorm",
        "current_node": "assistant-current",
        "mapping": {
            "root": {"id": "root", "parent": None, "children": ["user-1"], "message": None},
            "user-1": {
                "id": "user-1",
                "parent": "root",
                "children": ["assistant-current", "assistant-other"],
                "message": {
                    "id": "user-1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Brainstorm a local-first bridge."]},
                },
            },
            "assistant-current": {
                "id": "assistant-current",
                "parent": "user-1",
                "children": [],
                "message": {
                    "id": "assistant-current",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["Use generic session primitives."]},
                },
            },
            "assistant-other": {
                "id": "assistant-other",
                "parent": "user-1",
                "children": [],
                "message": {
                    "id": "assistant-other",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["This branch is not selected."]},
                },
            },
        },
    }


def test_conversation_reference_accepts_id_and_signed_in_web_url():
    assert conversation_id_from_reference(CONVERSATION_ID) == CONVERSATION_ID
    assert conversation_id_from_reference(f"https://chatgpt.com/c/{CONVERSATION_ID}") == CONVERSATION_ID
    with pytest.raises(ValueError, match="chatgpt.com"):
        conversation_id_from_reference(f"https://example.com/c/{CONVERSATION_ID}")


def test_compact_conversation_list_filters_titles_without_transcript_data():
    payload = {
        "items": [
            {
                "id": CONVERSATION_ID,
                "title": "Adaptive Agent Brainstorm",
                "update_time": 12,
                "mapping": {"private": "not returned"},
            },
            {
                "id": "87654321-abcd-4321-abcd-1234567890ab",
                "title": "Unrelated",
            },
        ]
    }

    result = compact_conversation_list(payload, query="agent")

    assert result == [
        {
            "id": CONVERSATION_ID,
            "title": "Adaptive Agent Brainstorm",
            "web_url": f"https://chatgpt.com/c/{CONVERSATION_ID}",
            "updated_at": 12,
        }
    ]


def test_current_branch_ignores_sibling_and_compacts_recent_messages():
    messages = current_branch_messages(_conversation())
    compacted, omitted = compact_branch(messages, max_messages=1, max_chars=1000)

    assert [message["text"] for message in messages] == [
        "Brainstorm a local-first bridge.",
        "Use generic session primitives.",
    ]
    assert compacted[0]["text"] == "Use generic session primitives."
    assert omitted == 1


def test_current_branch_assets_exclude_user_uploads_and_include_generated_tools():
    conversation = _conversation()
    conversation["mapping"]["user-1"]["message"]["content"]["parts"].append(
        {"asset_pointer": "file-service://user-upload"}
    )
    conversation["mapping"]["assistant-current"]["children"] = ["image-tool"]
    conversation["mapping"]["image-tool"] = {
        "id": "image-tool",
        "parent": "assistant-current",
        "children": [],
        "message": {
            "id": "image-tool",
            "author": {"role": "tool"},
            "content": {
                "content_type": "multimodal_text",
                "parts": [{"asset_pointer": "sediment://assistant-output"}],
            },
        },
    }
    conversation["current_node"] = "image-tool"

    assert current_branch_assets(conversation) == [
        {
            "message_id": "image-tool",
            "asset_pointer": "sediment://assistant-output",
        }
    ]


def test_normalized_conversation_exports_markdown_and_json(tmp_path):
    normalized = normalized_conversation(_conversation(), max_messages=20, max_chars=12_000)

    markdown = conversation_markdown(normalized)
    assert "# Adaptive agent brainstorm" in markdown
    assert "This branch is not selected." not in markdown

    markdown_path = write_conversation(tmp_path / "conversation.md", normalized, output_format="markdown")
    json_path = write_conversation(tmp_path / "conversation.json", normalized, output_format="json")
    assert "generic session primitives" in markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["current_node"] == "assistant-current"
