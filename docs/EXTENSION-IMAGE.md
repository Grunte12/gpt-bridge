# Experimental image worker — no computer-use service

This is a separate, opt-in MCP server and a small Manifest V3 extension. It uses
the ordinary ChatGPT composer in **one owner-paired tab**, not CDP, screenshots,
Playwright, browser-control MCP, captured requests or ChatGPT verification tokens.
The tab still has to remain open and logged in; this is not a browser-free API.

**One live image passed (2026-10-16, extension 0.1.5):** the owner-confirmed
`second` Plus tab completed job `f6c9497ce09c46afb48a427b201a90c9` through real
stdio MCP → extension → native Create image → MCP file receipt. The saved PNG is
1254 × 1254 and depicts the requested photorealistic red mug. A subsequent download
from ChatGPT's native image viewer was byte-identical, with SHA-256
`58b44e056552d2a6d0c1aec7861392520e336207acb56d89bbc5851bdda0ecf8`.
No manual download was needed for the successful MCP receipt. This verifies one
native-image result, not batch reliability, reference editing, GPT-6 Pro/High
selection or a highest-quality setting. No `main` operation occurred.

The first local attempt stopped before Send because contenteditable `innerText`
inserted extra blank lines. Whitespace-only normalization fixes that check without
accepting changed words. A later plain-chat request returned a 1024px PNG produced
by 3D-rendering tools, **not native image generation**; it was rejected as an
acceptance result and not marked complete in MCP.

The current Web UI also removed old response/Stop markers. Source 0.1.4 added the
observed accessible Conversation/turn headings and Stop label, plus an explicit
output-only recovery action after a content-script reload. It never regenerates.
The owner's temporary chat disabled Create image, while the same account's normal
chat enabled it. Version 0.1.5 therefore requires the actual native Create image
pill (`picture_v2`) in an otherwise empty composer before pairing or sending.
It does not treat a plain High prompt as image mode. The normal-chat test above
passed this native-image guard and file receipt. Do not use for batches yet.
Nothing here restores direct HTTP or proves which provider change caused its
failure. This extension is not a verification bypass.

## Automatic reconnect and status (extension 0.1.6)

Prefer MCP and extension operations for testing and ordinary use. Browser-control
tools are only for missing setup/UI capabilities, not routine generation or
polling. The extension retains the existing local key, client identity and paired
tab in private Chrome extension storage. Its authenticated heartbeat reconnects
that saved client after MCP restarts; it never copies ChatGPT cookies or tokens.
No additional daemon, tunnel, pairing file or batch queue was added.

### Multiple agent hosts: one worker, shared clients

Keep exactly one owning MCP command (without `--connect`) running. This machine
now keeps that command in one foreground terminal so it is not tied to a single
agent chat. The terminal must remain open; no login/background daemon is installed.
Configure Codex, Claude Code, Cursor, Antigravity and OpenCode
with the same Python/module plus `--account second --connect`. These lightweight
stdio MCP clients use the existing authenticated loopback worker; they never
open another listener, lock/reload queue state, or interrupt running work.
They expose the same three tools and share the one-in-flight guard. If the owner
worker is offline, calls fail without retry; clients do not start a replacement.
The local key stays in its existing private file, not agent configuration.
Environment proxies and HTTP redirects are disabled for client requests.

From a fresh checkout, install the optional MCP dependency first:

```sh
python -m pip install -e '.[mcp]'
# One owner only:
python -m chatgpt_api.extension_bridge --account second
# Every additional local agent:
python -m chatgpt_api.extension_bridge --account second --connect
```

Claude Code user registration example (substitute the checkout's Python path):

```sh
claude mcp add --scope user gpt-bridge-extension -- /absolute/checkout/.venv/bin/python -m chatgpt_api.extension_bridge --account second --connect
```

Existing sessions may need to reload/reconnect this MCP at a safe point. Do not
restart busy agents or create replacement sessions. Installed shared skills must
route image tasks to these tools rather than the legacy direct-image commands.

### Popup and reconnect state

The popup now shows ready, busy, offline, incomplete-tab and result states.
Ordinary reconnect hides the key form. A local-key rotation or explicitly choosing
**ลืมการจับคู่** still requires a new initial pairing; ordinary MCP restarts do not.
If the paired tab was closed, use **ตัวเลือก → เชื่อมแท็บนี้แทน — ใช้รหัสเดิม** on a
fresh normal chat. That reuses the saved key, but still requires confirming the
second account. It never silently selects another tab/account.

The 30-second alarm is restored when the worker starts. Reconnect can take one
alarm interval, and browser scheduling may delay it. A live server connection and
a ready image composer are separate states: MCP exposes `extension_online` and
`tab_ready`, and rejects new work when the last heartbeat says the tab is not
ready. Every actual send still rechecks the composer. Work interrupted by a server
restart remains interrupted and is never resubmitted automatically.

Two live idle-MCP restart cycles on 2026-10-16 reconnected through the installed
extension without a key entry, pairing action or browser-control call. Each
recovered `paired=true` and `extension_online=true` within 45 seconds. The existing
completed/missing tab correctly reported `tab_ready=false`; reconnect did not
pretend a new image could be submitted there.

Afterward, the surviving second-account test tab was prepared as a normal fresh
chat with native Create image. Saved-key relinking succeeded without key entry.
Luna submitted exactly one request through real stdio MCP and polled MCP only:
job `c4d34f62560140b2b6a8c73483b5d86a` completed with a 1254 × 1254 PNG of the
requested cobalt-blue bowl and yellow lemon, SHA-256
`83ec3bab2ae78530ab6471df12fc319d9f103d934ede484cd9d49f03db99b5e3`.
The lead inspected that local output. Browser control was used for extension
reload, fresh-chat setup and popup QA, not submitting or polling the image.
The test's original-download quality was not compared; its rendered-asset label
remains conservative.

## One-time setup on this machine

With the one owning worker running, register a shared MCP client:

```sh
codex mcp add gpt-bridge-extension -- /Users/grunte/Workspace/repos/gpt-bridge/.venv/bin/python -m chatgpt_api.extension_bridge --account second --connect
```

Reload the MCP connection if the host does not discover newly registered servers.
It exposes only `extension_status`, `extension_image`, and `extension_resolve`.
The owning worker listens on `127.0.0.1:18767` while it remains running. It is a
separate process/data directory; existing direct Bridge jobs are unaffected.

Host lifecycle is separate from extension reconnection: an enabled configuration
does not itself start a stdio server. After acceptance testing on 2026-10-16, the
temporary MCP client was stopped and the normal Codex registration was restored
enabled for `second`. Codex subsequently rediscovered the three tools without an
app restart. A direct call in the existing chat confirmed `paired=true`,
`extension_online=true` and the completed image receipt. No test daemon was left
running. `tab_ready=false` was expected because the paired tab held the completed
image conversation, not a fresh empty Create image composer.

1. In Chrome's Extensions page, enable Developer mode, then **Load unpacked**:
   `/Users/grunte/Workspace/repos/gpt-bridge/extensions/chatgpt-image`.
2. With the new MCP running, copy its local pairing key without displaying it:
   `pbcopy < /Users/grunte/.local/share/gpt-bridge/extension/second/extension-token`.
3. Open a **normal fresh ChatGPT chat** on `second`, choose **Create image** from
   the + menu, and leave its native pill as the only composer content. Do not use
   temporary chat. Open the extension popup, paste the key and pair that tab. This key
   is for the local Bridge only, **not** a ChatGPT token. Do not share it.
   Check the confirmation that the tab uses `second`, not `main`.

The experimental server rejects any runtime alias other than `second`, and the
extension checks the actual selected tab URL instead of trusting a supplied URL.
The signed-in account is still owner-confirmed, not independently checked. Reserve the
paired tab for Bridge work; do not type, switch accounts or change its model while
a job is running. Login and any verification remain manual.

## One bounded smoke test

Call `extension_status` first. When `extension_online=true` and `tab_ready=true`, call
`extension_image` once with `prompt` and `expected_model`. `expected_model` must
be **`Create image`**, matching the verified native image route. This is not a
claim that an image uses GPT-6 High/Pro or a specific rendering-quality setting.
The worker does not select another account or silently fall back to plain chat.

It inserts a request for **one image**, clicks native Send once, and waits up to
15 minutes. Poll `extension_status(job_id)` for the result. `complete` requires
actual validated PNG/JPEG/WebP bytes saved locally; the record includes dimensions,
SHA-256 and `image_path`. It never substitutes a screenshot. Currently it reads
the displayed image asset. Although the accepted test was byte-identical to the
native download, other outputs may differ; the worker does **not** claim
highest/original quality automatically.

No automatic retry occurs on selector mismatch, verification, failure, timeout,
tab closure or restart. Rejected/uncertain work must be checked in ChatGPT before
trying again. Visible verification challenges stop the worker for owner action;
it never solves them or automatically resends after you complete them. To release a stuck job, inspect ChatGPT, then call
`extension_resolve(job_id, inspected_chatgpt=true)`. This does not cancel upstream
generation. The extension checks terminal state before clearing its active slot,
including after a server restart; disconnect cannot silently drop running work.
Use the popup's saved-key relink option to change tabs, or explicitly forget the
pairing to clear its stored key. A fresh empty chat is
required for the next image; automatic conversation navigation and image editing
are intentionally not included in this first version.

If a UI fix required reloading the extension and the original completed chat,
keep the MCP server running and use **ตัวเลือก → รับภาพจากงานเดิม ไม่สร้างซ้ำ** in
the popup on that same paired tab. It only observes an existing claimed job and
a completed single-turn conversation, then receives its displayed image; it never
inserts text or clicks Send. The stored original job and visible user prompt must
match exactly apart from whitespace and the native image pill; legacy active jobs
without that stored context refuse recovery. A server restart
marks unfinished work interrupted and this recovery refuses that terminal state.

## Security and permissions

- Extension permissions: local storage, active-tab pairing, a 30-second alarm,
  localhost access, and a content script on `https://chatgpt.com/*`.
- No cookies, debugger, webRequest, remote scripts or credential extraction.
- Authenticated localhost endpoints only; non-extension web origins and unknown
  Host headers are rejected. Only the paired extension/tab/job can return output.
- The local pairing key is stored in extension storage and a mode-600 file.
  Anyone holding it can pair a worker and access its queued prompt: keep it private.
- Prompts/job state and generated images are private local files, not uploaded
  to another service. Sending a prompt still consumes the selected ChatGPT plan's
  normal usage. This avoids agent computer-use calls, not all browser execution.
- The unpacked extension currently pairs the `second` alias only. It neither reuses
  nor changes existing Bridge account captures.
- This is one in-flight image at a time, not a batch queue, cloud broker or
  tunnel. The existing 30-second Chrome alarm polls for work; dispatch is not
  instant and background-browser scheduling can add delay.

## Offline checks

```sh
.venv/bin/python -m pytest -q
node --test tests/extension_content.test.cjs tests/extension_worker.test.cjs tests/extension_popup.test.cjs
```

The DOM tests use synthetic fixtures. They prove guard/dispatch behavior, **not**
compatibility with today's live ChatGPT UI. If UI selectors change, fail closed
and update from fresh owner-supplied DOM evidence rather than guessing/retrying.

Verified on 2026-10-16: Node suites 63/63; targeted Python extension tests 18/18;
full Python suite 385 passed, 3 skipped, with one existing Starlette deprecation
warning. A subsequent sandboxed targeted rerun also passed; its pytest-cache write
permission warning was not a product-test failure.

Multi-host rollout verification on the same date: all 33 extension Python tests
passed, including shared-client/HTTP guards, no retries, and no second queue or
listener. Two real stdio `--connect` clients simultaneously shared one running
second-account worker, listed the same three tools, read the completed 1254px
receipt, and rejected resolve without inspection confirmation. No new image was
submitted. An isolated export of only the staged release files plus committed
baseline passed Python 332 tests (3 skipped) and Node 63 tests. The full local
working tree, including unrelated pending work, passed Python 400 (3 skipped).
