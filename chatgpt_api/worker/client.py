"""Small, loopback-only HTTP client used by worker utility commands."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from chatgpt_api.core.errors import ProviderError


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_worker_base_url(value: str) -> str:
    """Normalize and restrict worker traffic to a locally hosted Bridge API."""
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOCAL_HOSTS:
        raise ProviderError("worker --base-url must be an http(s) loopback URL (127.0.0.1, localhost, or ::1)")
    return base_url


def validate_worker_path(value: str) -> str:
    """Accept only an API-relative path; worker commands cannot become a proxy."""
    path = value.strip()
    parsed = urlparse(path)
    if not path.startswith("/") or parsed.scheme or parsed.netloc or path.startswith("//"):
        raise ProviderError("worker request PATH must be an API-relative path beginning with /")
    return path


@dataclass(slots=True)
class WorkerClient:
    base_url: str
    api_key: str | None = None
    timeout: float = 120.0

    def __post_init__(self) -> None:
        self.base_url = validate_worker_base_url(self.base_url)
        self.timeout = max(1.0, float(self.timeout))

    def url_for(self, path: str) -> str:
        return urljoin(self.base_url + "/", validate_worker_path(path).lstrip("/"))

    async def request_text(self, method: str, path: str, body: dict[str, object] | None = None) -> str:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.request(method.upper(), self.url_for(path), headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"worker could not reach the local Bridge API: {exc}") from exc
        if response.status_code >= 400:
            message = response.text[:500]
            try:
                payload = response.json()
                error = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except json.JSONDecodeError:
                pass
            raise ProviderError(f"worker API {method.upper()} {path} failed: HTTP {response.status_code}: {message}")
        return response.text

    async def request_json(self, method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
        text = await self.request_text(method, path, body)
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise ProviderError(f"worker API returned non-JSON response: {text[:300]}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("worker API returned an unexpected JSON payload")
        return payload
