"""In-process worker transport for one locally captured ChatGPT account."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chatgpt_api.api.config import OpenAICompatConfig
from chatgpt_api.api.openai_compat import (
    AccountRouter,
    _admin_status_response,
    _chat_completion,
    _image_edit,
    _image_generation,
    _models_response,
    _vision_request,
)
from chatgpt_api.core.errors import ProviderError
from chatgpt_api.providers.chatgpt.accounts import list_account_profiles, resolve_account_capture_path
from chatgpt_api.worker.storage import WorkerPaths


DEFAULT_AGENT_MODEL = "gpt-5-6-sol-high"


def resolve_direct_account(account: str | None = None, accounts_dir: Path | None = None) -> str:
    """Resolve exactly one local account without enabling routing."""
    selected = (account or os.environ.get("CHATGPT_ACCOUNT") or "").strip()
    if selected:
        try:
            capture_path = resolve_account_capture_path(selected, accounts_dir)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc
        if not capture_path.is_file():
            raise ProviderError(
                f"ChatGPT account capture for '{selected}' is not configured at {capture_path}. "
                "Run 'gpt-bridge setup' in your own terminal before using the direct worker."
            )
        return selected

    profiles = [profile for profile in list_account_profiles(accounts_dir) if profile.exists]
    if len(profiles) == 1:
        return profiles[0].name
    if not profiles:
        raise ProviderError(
            "no local ChatGPT account capture is configured; run 'gpt-bridge setup' "
            "in your own terminal"
        )
    names = ", ".join(profile.name for profile in profiles)
    raise ProviderError(
        f"multiple local account captures exist ({names}); set CHATGPT_ACCOUNT or pass --account "
        "so direct mode still uses exactly one account"
    )


@dataclass(slots=True)
class DirectWorkerClient:
    """Dispatch worker requests in-process instead of through a local HTTP server."""

    account: str | None = None
    accounts_dir: Path | None = None
    timeout: float = 5400.0

    def __post_init__(self) -> None:
        self.account = resolve_direct_account(self.account, self.accounts_dir)
        self.timeout = max(1.0, float(self.timeout))

    def config(self) -> OpenAICompatConfig:
        paths = WorkerPaths.default()
        return OpenAICompatConfig(
            account=str(self.account),
            accounts=(str(self.account),),
            accounts_dir=self.accounts_dir,
            account_strategy="sticky",
            model_fallback=None,
            temporary_chat=True,
            image_output_dir=paths.root / "images",
            research_output_dir=paths.root / "research",
            admin_db_path=paths.root / "worker.db",
            web_timeout=self.timeout,
        )

    async def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_method = method.upper()
        normalized_path = "/" + path.strip().lstrip("/")
        config = self.config()
        router = AccountRouter((str(self.account),), "sticky")
        payload: dict[str, Any]

        try:
            if normalized_method == "GET" and normalized_path in {"/models", "/v1/models"}:
                payload = _models_response(config)
            elif normalized_method == "GET" and normalized_path in {
                "/chatgpt/admin/status",
                "/v1/chatgpt/admin/status",
            }:
                payload = _admin_status_response(config, router)
                payload["transport"] = "direct"
            elif normalized_method == "GET" and normalized_path == "/health":
                payload = {
                    "ok": True,
                    "transport": "direct",
                    "account": self.account,
                    "accounts": [self.account],
                    "account_strategy": "sticky",
                }
            elif normalized_method == "POST" and normalized_path in {
                "/chat/completions",
                "/v1/chat/completions",
            }:
                payload = await _chat_completion(config, dict(body or {}), router)
            elif normalized_method == "POST" and normalized_path in {
                "/images/generations",
                "/v1/images/generations",
            }:
                payload = await _image_generation(config, dict(body or {}), router)
            elif normalized_method == "POST" and normalized_path in {
                "/images/edits",
                "/v1/images/edits",
            }:
                payload = await _image_edit(config, dict(body or {}), router)
            elif normalized_method == "POST" and normalized_path in {
                "/chatgpt/vision",
                "/v1/chatgpt/vision",
            }:
                payload = await _vision_request(config, dict(body or {}), router)
            else:
                raise ProviderError(
                    f"direct worker does not implement {normalized_method} {normalized_path}; "
                    "use `gpt-bridge worker --transport http ...` only when an HTTP API route is required"
                )
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc
        return payload
