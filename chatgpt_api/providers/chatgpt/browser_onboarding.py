"""Visible, user-consented local browser onboarding.

This module deliberately does not automate sign-in, inspect an existing browser
profile, solve challenges, or print session material.  It opens an isolated
temporary profile and waits for the user to complete a normal browser action.
The resulting request is kept only in memory and returned to the caller for
the existing encrypted local-capture save path.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chatgpt_api.core.errors import ProviderError


_CONVERSATION_URL = "https://chatgpt.com/backend-api/f/conversation"


@dataclass(frozen=True)
class BrowserOnboardingResult:
    """An in-memory request capture; never serialize or log this object."""

    capture_text: str


def capture_from_visible_browser(*, accounts_dir: Path, timeout_seconds: int = 600) -> BrowserOnboardingResult:
    """Wait for one user-initiated conversation request in an isolated browser.

    Chrome is intentionally visible and uses a throwaway profile. The user
    performs all sign-in and challenge steps themselves. If Chrome is not
    installed, the first run fetches Playwright's bundled Chromium and retries.
    """

    from playwright.sync_api import sync_playwright

    accounts_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix=".onboarding-", dir=accounts_dir))
    captured: dict[str, str] = {}
    found = threading.Event()

    try:
        with sync_playwright() as playwright:
            context = _launch_visible_context(playwright, profile_dir)

            def on_request(request: Any) -> None:
                if request.method != "POST" or request.url.split("?", 1)[0] != _CONVERSATION_URL or found.is_set():
                    return
                try:
                    headers = request.all_headers()
                    cookies = context.cookies("https://chatgpt.com")
                    cookie_header = "; ".join(
                        f"{cookie['name']}={cookie['value']}" for cookie in cookies if cookie.get("name") and cookie.get("value")
                    )
                    if cookie_header:
                        headers["cookie"] = cookie_header
                    capture = _capture_text(request.url, headers, request.post_data or "")
                    if "authorization" in {str(key).lower() for key in headers} and cookie_header and request.post_data:
                        captured["text"] = capture
                        found.set()
                except Exception:
                    # A partial browser event must not create a durable session or
                    # surface secret-bearing diagnostics.
                    return

            context.on("request", on_request)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded")
            deadline = time.monotonic() + timeout_seconds
            while not found.wait(0.2):
                if time.monotonic() >= deadline:
                    raise ProviderError(
                        "no usable user-initiated conversation request was observed before timeout; "
                        "nothing was saved"
                    )
            context.close()
    finally:
        # A temp profile can contain cookies and browser cache.  Remove it on
        # success, cancellation, timeout, and browser failure.  This is normal
        # filesystem deletion, not a claim of guaranteed SSD secure erasure.
        shutil.rmtree(profile_dir, ignore_errors=True)

    capture_text = captured.get("text")
    if not capture_text:
        raise ProviderError("browser onboarding ended without a valid capture; nothing was saved")
    return BrowserOnboardingResult(capture_text=capture_text)


def _capture_text(url: str, headers: dict[str, str], request_data: str) -> str:
    """Encode only in memory in the existing parser's neutral text format."""

    safe_headers = [f"{name}: {value}" for name, value in headers.items()]
    return "\n".join(["URL: " + url, *safe_headers, "Request Data: " + request_data])


def _launch_visible_context(playwright: Any, profile_dir: Path) -> Any:
    options = {"headless": False, "accept_downloads": False, "args": ["--disable-extensions"]}
    try:
        return playwright.chromium.launch_persistent_context(str(profile_dir), channel="chrome", **options)
    except Exception:
        try:
            return playwright.chromium.launch_persistent_context(str(profile_dir), **options)
        except Exception:
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    stdin=subprocess.DEVNULL,
                )
                return playwright.chromium.launch_persistent_context(str(profile_dir), **options)
            except Exception as exc:
                raise ProviderError(
                    "could not start a visible browser for local onboarding; Chrome/Chromium setup failed and nothing was saved"
                ) from exc
