"""Normalize ChatGPT Web conversations for compact agent workflows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_CHATGPT_HOSTS = {"chatgpt.com", "www.chatgpt.com", "chat.openai.com"}


def conversation_id_from_reference(reference: str) -> str:
    """Accept a raw conversation id or a signed-in ChatGPT `/c/<id>` URL."""
    value = reference.strip()
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.hostname not in _CHATGPT_HOSTS:
            raise ValueError("conversation URL must use https://chatgpt.com/c/<id>")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0] != "c":
            raise ValueError("conversation URL must use https://chatgpt.com/c/<id>")
        value = parts[1]
    if not _CONVERSATION_ID_RE.fullmatch(value):
        raise ValueError("conversation must be a ChatGPT conversation id or https://chatgpt.com/c/<id> URL")
    return value


def conversation_web_url(conversation_id: str) -> str:
    return f"https://chatgpt.com/c/{conversation_id_from_reference(conversation_id)}"


def compact_conversation_list(
    payload: dict[str, Any],
    *,
    query: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return only metadata an agent needs to select a conversation."""
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = payload.get("conversations")
    if not isinstance(raw_items, list):
        return []
    needle = (query or "").strip().casefold()
    compact_needle = _search_key(needle)
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        conversation_id = raw.get("id")
        if not isinstance(conversation_id, str) or not _CONVERSATION_ID_RE.fullmatch(conversation_id):
            continue
        title = raw.get("title") if isinstance(raw.get("title"), str) else "Untitled"
        if needle:
            normalized_title = title.casefold()
            if needle not in normalized_title and compact_needle not in _search_key(normalized_title):
                continue
        item: dict[str, Any] = {
            "id": conversation_id,
            "title": title,
            "web_url": conversation_web_url(conversation_id),
        }
        for source, target in (
            ("update_time", "updated_at"),
            ("create_time", "created_at"),
            ("is_archived", "archived"),
        ):
            if raw.get(source) is not None:
                item[target] = raw[source]
        items.append(item)
        if limit is not None and len(items) >= limit:
            break
    return items


def current_conversation_node(payload: dict[str, Any]) -> str:
    current = payload.get("current_node")
    mapping = payload.get("mapping")
    if not isinstance(current, str) or not isinstance(mapping, dict) or current not in mapping:
        raise ValueError("ChatGPT conversation did not include a valid current branch")
    return current


def current_branch_messages(
    payload: dict[str, Any],
    *,
    include_internal: bool = False,
) -> list[dict[str, Any]]:
    """Walk the selected ChatGPT branch from root to current node."""
    messages: list[dict[str, Any]] = []
    for node in _current_branch_nodes(payload):
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        author = message.get("author")
        role = author.get("role") if isinstance(author, dict) else None
        if not isinstance(role, str):
            role = "unknown"
        if not include_internal and role not in {"user", "assistant"}:
            continue
        text = _message_text(message)
        if not text:
            continue
        normalized: dict[str, Any] = {
            "id": str(message.get("id") or node.get("id") or ""),
            "role": role,
            "text": text,
        }
        if message.get("create_time") is not None:
            normalized["created_at"] = message["create_time"]
        content = message.get("content")
        if isinstance(content, dict) and isinstance(content.get("content_type"), str):
            normalized["content_type"] = content["content_type"]
        messages.append(normalized)
    return messages


def current_branch_assets(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Return generated assistant/tool assets while excluding user uploads."""
    assets: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in _current_branch_nodes(payload):
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        author = message.get("author")
        if not isinstance(author, dict) or author.get("role") not in {"assistant", "tool"}:
            continue
        message_id = str(message.get("id") or node.get("id") or "")
        for pointer in _asset_pointers(message):
            if pointer in seen:
                continue
            seen.add(pointer)
            assets.append({"message_id": message_id, "asset_pointer": pointer})
    return assets


def compact_branch(
    messages: list[dict[str, Any]],
    *,
    max_messages: int = 20,
    max_chars: int = 12_000,
) -> tuple[list[dict[str, Any]], int]:
    """Keep the most recent branch content within explicit context limits."""
    selected = list(messages)
    if max_messages > 0:
        selected = selected[-max_messages:]
    omitted = len(messages) - len(selected)
    if max_chars <= 0:
        return selected, omitted
    while len(selected) > 1 and sum(len(str(item.get("text") or "")) for item in selected) > max_chars:
        selected.pop(0)
        omitted += 1
    if selected:
        text = str(selected[-1].get("text") or "")
        total = sum(len(str(item.get("text") or "")) for item in selected)
        overflow = total - max_chars
        if overflow > 0:
            keep = max(0, len(text) - overflow)
            selected[-1] = {**selected[-1], "text": text[:keep].rstrip() + "\n[…truncated]"}
    return selected, omitted


def normalized_conversation(
    payload: dict[str, Any],
    *,
    include_internal: bool = False,
    max_messages: int = 20,
    max_chars: int = 12_000,
) -> dict[str, Any]:
    conversation_id = conversation_id_from_reference(str(payload.get("id") or ""))
    messages = current_branch_messages(payload, include_internal=include_internal)
    compacted, omitted = compact_branch(messages, max_messages=max_messages, max_chars=max_chars)
    return {
        "object": "chatgpt.web.conversation",
        "id": conversation_id,
        "title": payload.get("title") if isinstance(payload.get("title"), str) else "Untitled",
        "web_url": conversation_web_url(conversation_id),
        "current_node": current_conversation_node(payload),
        "message_count": len(messages),
        "omitted_messages": omitted,
        "messages": compacted,
    }


def conversation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload.get('title') or 'Untitled'}",
        "",
        f"ChatGPT Web: {payload.get('web_url')}",
        "",
    ]
    omitted = int(payload.get("omitted_messages") or 0)
    if omitted:
        lines.extend([f"_Omitted {omitted} earlier messages due to the requested limits._", ""])
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "unknown").replace("_", " ").title()
            lines.extend([f"## {role}", "", str(message.get("text") or ""), ""])
    return "\n".join(lines).rstrip() + "\n"


def write_conversation(
    output: Path,
    payload: dict[str, Any],
    *,
    output_format: str,
) -> Path:
    target = output.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    elif output_format == "markdown":
        content = conversation_markdown(payload)
    else:
        raise ValueError("conversation output format must be markdown or json")
    target.write_text(content, encoding="utf-8")
    return target.resolve()


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        text = content.get("text")
        return text.strip() if isinstance(text, str) else ""
    values: list[str] = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            values.append(part.strip())
            continue
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            values.append(text.strip())
            continue
        asset_pointer = part.get("asset_pointer")
        if isinstance(asset_pointer, str):
            values.append("[image or file asset]")
    return "\n\n".join(values).strip()


def _search_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _current_branch_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = payload.get("mapping")
    current = current_conversation_node(payload)
    assert isinstance(mapping, dict)
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current:
        if current in seen:
            raise ValueError("ChatGPT conversation branch contains a cycle")
        seen.add(current)
        node = mapping.get(current)
        if not isinstance(node, dict):
            raise ValueError("ChatGPT conversation branch references a missing node")
        nodes.append(node)
        parent = node.get("parent")
        current = parent if isinstance(parent, str) else ""
    nodes.reverse()
    return nodes


def _asset_pointers(value: Any) -> list[str]:
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            pointer = item.get("asset_pointer")
            if isinstance(pointer, str) and pointer.startswith(("file-service://", "sediment://")):
                found.append(pointer)
            for nested in item.values():
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)

    walk(value)
    return found
