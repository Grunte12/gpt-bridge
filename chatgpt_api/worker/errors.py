"""Actionable, non-auth-automating guidance for common Bridge failures."""

from __future__ import annotations


_GUIDANCE = {
    "chatgpt_model_limit": "This ChatGPT model has reached its usage cap. Wait for reset or choose another exposed model.",
    "chatgpt_rate_limited": "ChatGPT is rate-limiting the bridge. Wait briefly and retry with a lower request rate.",
    "chatgpt_unsupported_model": "The requested model is unavailable. Run `gpt-bridge worker doctor` to inspect exposed models.",
    "chatgpt_auth_or_browser_challenge": (
        "The saved ChatGPT session is no longer valid. Refresh the capture yourself through the admin capture flow; "
        "the worker never reads, stores, or replays browser captures."
    ),
    "chatgpt_blocked_features": "The requested feature is unavailable for this ChatGPT account or plan.",
    "network_error": "The local Bridge API is not reachable. Check its service status and worker --base-url.",
    "aborted": "The request ended before the Bridge API responded. Retry; persistent failures may indicate overload.",
}


def explain_worker_error(error: object) -> str:
    """Return a concise human action for an API-style error object."""
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and code in _GUIDANCE:
        return _GUIDANCE[code]
    if isinstance(code, str) and code.startswith("http_") and len(code) == 8 and code[-3:].isdigit():
        status = int(code[-3:])
        if 400 <= status < 500:
            return "The Bridge API rejected this request. Check the path, flags, and request body."
        if 500 <= status < 600:
            return "The Bridge API had a server-side failure. Retry, then inspect its logs if it persists."
    return "No specific guidance is available; inspect the raw error and local Bridge API logs."
