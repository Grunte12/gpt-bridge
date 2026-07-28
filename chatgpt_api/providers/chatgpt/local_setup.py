"""One-shot loopback setup page for user-controlled request capture.

The page opens in the user's normal browser. Sensitive capture text is posted
only to a random, process-local loopback URL, kept in memory, and never logged.
The server exits immediately after receiving one structurally valid capture.
"""

from __future__ import annotations

import json
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import urlparse

from chatgpt_api.core.errors import ProviderError
from chatgpt_api.providers.chatgpt.request_capture import CapturedRequest


_MAX_CAPTURE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class LocalSetupResult:
    """One in-memory capture returned to the encrypted save path."""

    capture_text: str


@dataclass
class _SetupState:
    token: str
    capture_text: str | None = None


def capture_from_local_setup_page(
    *,
    timeout_seconds: int = 600,
    opener: Callable[[str], object] = webbrowser.open,
    announce: Callable[[str], None] | None = None,
) -> LocalSetupResult:
    """Open a normal-browser setup page and wait for one private local paste."""

    state = _SetupState(token=secrets.token_urlsafe(32))
    handler = _handler_class(state)
    try:
        server = HTTPServer(("127.0.0.1", 0), handler)
    except OSError as exc:
        raise ProviderError("could not start the temporary local setup page") from exc

    server.timeout = 0.2
    url = f"http://127.0.0.1:{server.server_port}/setup/{state.token}"
    if announce is not None:
        announce(f"Local setup page: {url}")
    try:
        opener(url)
        deadline = time.monotonic() + timeout_seconds
        while state.capture_text is None:
            if time.monotonic() >= deadline:
                raise ProviderError("local setup timed out; nothing was saved")
            server.handle_request()
    finally:
        server.server_close()

    return LocalSetupResult(capture_text=state.capture_text)


def _handler_class(state: _SetupState) -> type[BaseHTTPRequestHandler]:
    class LocalSetupHandler(BaseHTTPRequestHandler):
        server_version = "GPTBridgeSetup/1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            if self.path != f"/setup/{state.token}":
                self._send_text(404, "Not found")
                return
            body = _setup_html(state.token).encode("utf-8")
            self.send_response(200)
            self._security_headers("text/html; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            if self.path != f"/submit/{state.token}" or state.capture_text is not None:
                self._send_json(404, {"ok": False, "error": "Setup session is not available."})
                return
            expected_origin = f"http://127.0.0.1:{self.server.server_port}"
            origin = self.headers.get("Origin")
            if origin and origin != expected_origin:
                self._send_json(403, {"ok": False, "error": "Origin was rejected."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_CAPTURE_BYTES:
                self._send_json(413, {"ok": False, "error": "Capture is empty or too large."})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                capture_text = payload.get("capture_text", "") if isinstance(payload, dict) else ""
                if not isinstance(capture_text, str) or not capture_text.strip():
                    raise ValueError("Paste one complete request capture.")
                capture = CapturedRequest.from_text(capture_text)
                _validate_capture_shape(capture)
            except (UnicodeError, json.JSONDecodeError, ValueError, ProviderError) as exc:
                self._send_json(400, {"ok": False, "error": _safe_error(exc)})
                return
            state.capture_text = capture_text
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Capture received locally. You may close this tab and return to the terminal.",
                },
            )

        def log_message(self, format: str, *args: object) -> None:
            return

        def _security_headers(self, content_type: str, content_length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
            )

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._security_headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, status: int, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self._security_headers("text/plain; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

    return LocalSetupHandler


def _validate_capture_shape(capture: CapturedRequest) -> None:
    parsed = urlparse(capture.url)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "www.chatgpt.com"}:
        raise ValueError("The pasted request must come from chatgpt.com.")
    if "/backend-api/" not in parsed.path:
        raise ValueError("Select a ChatGPT backend conversation request.")
    if not capture.headers.get("authorization"):
        raise ValueError("Authorization is missing; copy the complete request as cURL.")
    if not capture.cookies:
        raise ValueError("Cookies are missing; copy the complete request as cURL.")


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message or len(message) > 240:
        return "Capture validation failed. Copy one complete ChatGPT conversation request as cURL."
    return message


def _setup_html(token: str) -> str:
    submit_path = f"/submit/{token}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GPT Bridge Setup</title>
  <style>
    :root {{ color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; background: #0b1020; color: #e8edf7; }}
    main {{ width: min(920px, calc(100% - 32px)); margin: 40px auto; }}
    .card {{ background: #151c31; border: 1px solid #2b3656; border-radius: 18px; padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    p, li {{ line-height: 1.55; color: #bfc9dc; }}
    a {{ color: #8eb5ff; }}
    textarea {{ width: 100%; min-height: 260px; box-sizing: border-box; resize: vertical;
      border: 1px solid #3b496e; border-radius: 12px; padding: 14px; background: #0d1427;
      color: #f4f7ff; font: 13px ui-monospace, SFMono-Regular, monospace; }}
    button {{ margin-top: 14px; border: 0; border-radius: 10px; padding: 12px 18px;
      background: #5c8dff; color: #071021; font-weight: 750; cursor: pointer; }}
    button:disabled {{ opacity: .55; cursor: wait; }}
    #status {{ min-height: 24px; margin-top: 12px; color: #a9c3ff; }}
    .warning {{ padding: 12px 14px; border-radius: 10px; background: #2b2030; color: #ffd6df; }}
    code {{ color: #dbe6ff; }}
  </style>
</head>
<body>
<main>
  <div class="card">
    <h1>GPT Bridge local setup</h1>
    <p>This one-time page runs only on <code>127.0.0.1</code> and closes with the command.
      It does not upload or display your capture anywhere else.</p>
    <ol>
      <li><a href="https://chatgpt.com/" target="_blank" rel="noreferrer">Open ChatGPT</a>
        in this normal browser and send one short message.</li>
      <li>Open DevTools → Network, select the <code>conversation</code> request,
        then right-click → Copy → <strong>Copy as cURL</strong>.</li>
      <li>Paste it below and click <strong>Validate &amp; Save locally</strong>.</li>
    </ol>
    <p class="warning">Treat the copied request like a password. Never paste it into chat,
      commit it, or send it to another person.</p>
    <textarea id="capture" autocomplete="off" spellcheck="false"
      placeholder="Paste one complete Copy as cURL request here"></textarea>
    <button id="save" type="button">Validate &amp; Save locally</button>
    <div id="status" role="status" aria-live="polite"></div>
  </div>
</main>
<script>
  const capture = document.getElementById("capture");
  const save = document.getElementById("save");
  const status = document.getElementById("status");
  save.addEventListener("click", async () => {{
    if (!capture.value.trim()) {{ status.textContent = "Paste one complete request first."; return; }}
    save.disabled = true;
    status.textContent = "Validating locally…";
    try {{
      const response = await fetch({json.dumps(submit_path)}, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ capture_text: capture.value }})
      }});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Capture validation failed.");
      capture.value = "";
      status.textContent = result.message;
      save.textContent = "Saved";
    }} catch (error) {{
      status.textContent = error.message || String(error);
      save.disabled = false;
    }}
  }});
</script>
</body>
</html>"""
