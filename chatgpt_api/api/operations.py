"""State tracking and cancellation for long-running GPT Bridge operations."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from chatgpt_api.core.errors import ProviderError

if TYPE_CHECKING:
    from chatgpt_api.providers.chatgpt.provider import ChatGPTProvider


@dataclass(slots=True)
class ChatGPTOperation:
    operation_id: str
    kind: str
    created_at: float
    account: str | None = None
    provider: ChatGPTProvider | None = None
    conversation_id: str | None = None
    deep_research_message_id: str | None = None
    deep_research_session_id: str | None = None
    cancel_requested: bool = False
    completed: bool = False
    last_cancel_result: dict[str, Any] | None = None
    last_cancel_error: str | None = None


CHATGPT_OPERATIONS: dict[str, ChatGPTOperation] = {}
CHATGPT_OPERATIONS_LOCK = threading.Lock()
CHATGPT_OPERATION_TTL_SECONDS = 3600.0


def prune_chatgpt_operations(now: float | None = None) -> None:
    cutoff = (now or time.time()) - CHATGPT_OPERATION_TTL_SECONDS
    with CHATGPT_OPERATIONS_LOCK:
        stale = [
            operation_id
            for operation_id, operation in CHATGPT_OPERATIONS.items()
            if operation.created_at < cutoff and operation.completed
        ]
        for operation_id in stale:
            CHATGPT_OPERATIONS.pop(operation_id, None)


def create_chatgpt_operation(kind: str, operation_id: str | None = None) -> ChatGPTOperation:
    prune_chatgpt_operations()
    operation = ChatGPTOperation(
        operation_id=operation_id or f"chatgptop_{uuid.uuid4().hex}",
        kind=kind,
        created_at=time.time(),
    )
    with CHATGPT_OPERATIONS_LOCK:
        CHATGPT_OPERATIONS[operation.operation_id] = operation
    return operation


def update_chatgpt_operation(operation_id: str | None, **updates: Any) -> ChatGPTOperation | None:
    if not operation_id:
        return None
    with CHATGPT_OPERATIONS_LOCK:
        operation = CHATGPT_OPERATIONS.get(operation_id)
        if operation is None:
            return None
        for key, value in updates.items():
            if hasattr(operation, key):
                setattr(operation, key, value)
        return operation


def finish_chatgpt_operation(operation_id: str | None) -> None:
    update_chatgpt_operation(operation_id, completed=True)


def chatgpt_operation_cancel_requested(operation_id: str | None) -> bool:
    if not operation_id:
        return False
    with CHATGPT_OPERATIONS_LOCK:
        operation = CHATGPT_OPERATIONS.get(operation_id)
        return bool(operation and operation.cancel_requested)


def chatgpt_operation_payload(operation: ChatGPTOperation) -> dict[str, Any]:
    deep_research_ready = bool(
        operation.conversation_id and operation.deep_research_message_id and operation.deep_research_session_id
    )
    pending_reason = None
    if operation.kind == "research" and not operation.completed and not deep_research_ready:
        if not operation.provider:
            pending_reason = "provider_not_selected"
        elif not operation.conversation_id:
            pending_reason = "conversation_id_not_available"
        else:
            pending_reason = "deep_research_session_not_available"
    return {
        "id": operation.operation_id,
        "kind": operation.kind,
        "account": operation.account,
        "provider_selected": bool(operation.provider),
        "conversation_id": operation.conversation_id,
        "deep_research_message_id": operation.deep_research_message_id,
        "deep_research_session_id": operation.deep_research_session_id,
        "deep_research_ready": deep_research_ready,
        "pending_reason": pending_reason,
        "cancel_requested": operation.cancel_requested,
        "completed": operation.completed,
        "last_cancel_result": operation.last_cancel_result,
        "last_cancel_error": operation.last_cancel_error,
    }


def get_chatgpt_operation(operation_id: str) -> tuple[int, dict[str, Any]]:
    prune_chatgpt_operations()
    with CHATGPT_OPERATIONS_LOCK:
        operation = CHATGPT_OPERATIONS.get(operation_id)
        if operation is None:
            return 404, {"error": {"message": "operation not found", "type": "not_found"}}
        return 200, {"object": "chatgpt.operation", "operation": chatgpt_operation_payload(operation)}


def stop_chatgpt_operation_by_id(operation_id: str | None) -> ChatGPTOperation | None:
    if not operation_id:
        return None
    with CHATGPT_OPERATIONS_LOCK:
        operation = CHATGPT_OPERATIONS.get(operation_id)
    if operation is None:
        return None
    return stop_chatgpt_operation(operation)


def cancel_chatgpt_operation(operation_id: str) -> tuple[int, dict[str, Any]]:
    with CHATGPT_OPERATIONS_LOCK:
        operation = CHATGPT_OPERATIONS.get(operation_id)
        if operation is None:
            return 404, {"error": {"message": "operation not found", "type": "not_found"}}
        operation.cancel_requested = True

    result = stop_chatgpt_operation(operation)
    return 200, {"status": "ok", "operation": chatgpt_operation_payload(result)}


def stop_chatgpt_operation(operation: ChatGPTOperation) -> ChatGPTOperation:
    cancel_result: dict[str, Any] = {}
    cancel_errors: list[str] = []
    provider = operation.provider
    if provider is None:
        cancel_result["pending"] = "provider_not_selected"
    else:
        if operation.conversation_id:
            try:
                cancel_result["conversation"] = provider.transport.stop_conversation(
                    operation.conversation_id,
                    exclude_async_types=["pro_mode"],
                )
            except ProviderError as exc:
                cancel_errors.append(str(exc))
        else:
            cancel_result["pending"] = "conversation_id_not_available"
        if operation.conversation_id and operation.deep_research_message_id and operation.deep_research_session_id:
            try:
                cancel_result["deep_research"] = provider.transport.stop_deep_research(
                    operation.conversation_id,
                    operation.deep_research_message_id,
                    operation.deep_research_session_id,
                )
            except ProviderError as exc:
                cancel_errors.append(str(exc))
        elif operation.kind == "research":
            cancel_result["deep_research_pending"] = "widget_session_id_not_available"

    with CHATGPT_OPERATIONS_LOCK:
        current = CHATGPT_OPERATIONS.get(operation.operation_id)
        if current is None:
            return operation
        current.last_cancel_result = cancel_result
        current.last_cancel_error = "; ".join(cancel_errors) if cancel_errors else None
        return current
