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
They expose the same four tools and share the one-in-flight guard. If the owner
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

Live host acceptance on 2026-10-16 is separate from configuration installation:
OpenCode, Cursor and Antigravity each called native `extension_status` from an
existing conversation and read the completed second-account 1254 × 1254 receipt.
OpenCode used its supported dynamic MCP registration endpoint on the existing
server; the two closed desktop apps were opened and their existing chats reused.
No agent conversation was created, running job stopped, or new image generated.
The owner's later Claude Code screenshot confirms its new MCP is loaded and the
extension is online. Codex subsequently called native `extension_status` in this
existing chat successfully too. These are connection checks, not evidence that
every host has generated a new image with automatic preparation.

### Automatic next-image preparation (extension 0.1.7)

An explicitly submitted new image job now prepares its own native image chat in
the same owner-paired tab. If the tab contains a completed conversation, the
extension clicks native New chat, then Add files and more → Create image, and
verifies the actual `picture_v2` pill before inserting the prompt or clicking
Send. Old conversations stay in ChatGPT history. No preparation or navigation
happens during idle heartbeats, and no replacement tab is created.

`tab_ready=false` is a snapshot, not a reason to ask the owner to prepare every
image. Submit only when `account=second`, `paired=true`, `extension_online=true`
and no nonterminal job exists. Preparation refuses a draft, attachments, running
work, temporary chat, verification screen, missing controls or a closed paired
tab. It does not clear input, interrupt work, switch accounts, or solve challenges.
Login/verification and initial pairing remain manual.

The Web app can retain an old hidden composer before the current visible one
after New chat. Composer lookup must inspect all matching editors and select a
visible match; selecting the first DOM match can time out even on an empty chat.
After an extension update, reload the extension and refresh the paired tab once
so its content script is current. This update step is not per-image preparation.
Chrome may also redact a paired tab's URL after an extension reload. In that
case the worker requires a response from its existing ChatGPT-only content
receiver before claiming work; it does not request broader browser permissions.

Live acceptance passed after selecting the visible composer and confirming the
updated content script was actually loaded. Luna generated two consecutive
independent images through native MCP only: `49354183d6b941f3a2e010b0a0dbea01`
(blue vase) and `f67c5bee10f847d8a3cb703a89058299` (yellow mug), both validated
1254 × 1254 PNGs. The lead inspected both files. No browser preparation was needed
between requests. The existing Claude Code Adobe stock conversation then passed
two real production requests, `78d03a33dae046c2aa0d6c17381ff664` and
`a1cba268345a4f94834a6c30e677a4b0`, both 1448 × 1086, with the same MCP-only flow.
No failed job was automatically replayed and no `main` operation occurred.

An `interrupted` job is terminal and does not, by itself, occupy the worker's
in-flight capacity. Do not ask the owner to clear terminal history as a readiness
fix. Inspect uncertain upstream work before retrying; never automatically replay
an interrupted request. A newly authorized independent job is not a replay.

### Saved-image chat cleanup (extension 0.1.8)

Each image uses a fresh chat. After the local worker validates and saves the
image bytes and returns the file receipt, the extension opens the native Delete
confirmation for only that generated chat. It checks the exact paired job, live
chat path, single-turn conversation and original prompt before opening the menu.
The native Create image badge is excluded from prompt comparison, including its
saved-message markup. Chrome's MessageSender URL can retain an older SPA path;
the content receiver therefore verifies the current path itself.

Permanent deletion still requires the owner's action-time confirmation for the
exact saved-image chat. Version 0.1.8 required a human click in the native dialog;
version 0.1.9 adds the job-scoped MCP action below, without browser-control tools.
`state=complete` means the image is saved, while `cleanup_status` separately shows:

- `pending`: file saved; cleanup is being checked.
- `confirmation_required`: native Delete dialog is open; request owner approval
  for this job and its `chat_path`, then call `extension_confirm_delete` once.
- `deleted`: the native confirmation was clicked and the chat navigated away.
- `failed`: cleanup was cancelled, timed out or could not be verified; the saved
  file remains valid. Inspect the existing chat; do not regenerate or retry
  deletion automatically.

During confirmation the worker keeps its authenticated heartbeat online but
does not claim another image or change the tab. Unrelated navigation is not
treated as successful deletion. No unrelated old conversation is cleaned up.
Cleanup canaries saved their images but exposed sender-path, native-badge and
menu-trigger checks. The More menu is a pointerdown trigger; a programmatic click
alone did not open it. These checks were fixed without resubmitting any
saved-image request.

The updated native MCP canary `eab8f1c58a1a4dd8a3ffb0713ca7a402` saved a
1254 × 1254 apple PNG and reached `confirmation_required` automatically. Its
SHA-256 is `49e847b629688c7a849e84b165c8ade736f30f617388f69947eb56429231f5fa`.
Claude Code independently read the receipt through its existing native MCP and
matched the on-disk hash and dimensions. After the owner explicitly approved
this exact chat at action time, the lead clicked its native final Delete chat
button. MCP reported `cleanup_status=deleted`, ChatGPT returned to its empty
home composer, and the saved file's SHA-256 remained unchanged. This verifies the
confirmation-gated flow, not unattended permanent deletion. Offline checks pass:
102 extension tests and 42 worker/client tests at that version.

### Job-scoped deletion through MCP (extension 0.1.9)

After the image is saved, inspect `extension_status(job_id=...)` and show the
owner that job's `chat_path`. Request approval for permanent deletion of this
exact generated chat. Only after actual action-time approval, call
`extension_confirm_delete(job_id=..., owner_confirmed=true)` once and poll the
same status until `cleanup_status=deleted` or a reported failure. The extension
consumes the persisted approval once, rechecks the original native dialog and
idle composer, then clicks its final Delete button. Browser control is not part
of this functional route. A trusted owner click in the native dialog also works.

Pending cleanup rejects another image submission or a pairing change; it does
not silently queue work behind a confirmation dialog. A worker restart marks
unfinished cleanup failed and invalidates any approval, preserving the saved
image and hash. Do not repeat an uncertain deletion. Updating the owner worker
and extension does not update the tool schema of an already-running stdio MCP
client: reconnect that client's MCP safely, without restarting its conversation.

Offline verification: 112 extension tests and 55 worker/client tests pass.
Luna's live stdio MCP-only canary `aadda8f2719f462abb3b131784f82ce4`
generated an emerald-green cup and saved a 1374 × 1145 PNG, SHA-256
`badde575454ce7db46e4ffa1ec435dbb23fe0be8c09422d220739e09c8775f59`.
After the owner approved this exact chat, Luna called `extension_confirm_delete`
once. MCP reported `cleanup_status=deleted` and
`cleanup_confirmation=consumed`; the local PNG retained its dimensions and hash.
No browser-control action was used for generation, receipt, confirmation or
deletion. Browser control was used only to reload the installed extension and
refresh its content script before the test.

The existing Claude Code Adobe session independently verified that saved-file
receipt and on-disk hash. Its transport transparently respawned after an idle
stdio client restart, but the desktop host retained its cached three-tool list.
Even a correctly negotiated `tools.listChanged=true` and one real
`notifications/tools/list_changed` did not refresh that session's list; that
ineffective workaround was removed. Its local-server panel has no reconnect
control. Reopen/resume the same saved Claude session at an idle point to load
the fourth tool; do not repeatedly restart transports, create a replacement
conversation, or claim that extension reconnect alone refreshes host schemas.
After the owner reopened the same Adobe session, Claude supplied native
ToolSearch metadata for all four tools, including `extension_resolve`. Its real
production job `abbff561606240528950570699b42872` saved a 1448 × 1086 PNG with
SHA-256 `2dd6beb3e295d10d57bb184fdd7fe96f40c5fe6d0dcea32b959fb9fa61d4c625`.
Cleanup expired after the 15-minute confirmation window and was handled manually
by the owner. The next saved job, `475455182ca9476a8e2603a8583b058f`, reached
`cleanup_status=deleted` through Claude's native MCP after owner approval.

### Owner-authorized automatic cleanup (0.1.10)

The owner explicitly requested permanent automatic deletion of Bridge-created
image-generation chats after validated local saves, without per-image questions.
Enable this only on the owning worker:

```sh
python -m chatgpt_api.extension_bridge --account second --auto-delete-saved-chats
```

Other clients keep `--account second --connect`; no new tools, listeners or queues
are added. Live status reports `cleanup_policy=automatic_saved_chats`. The default
without this flag remains `per_job_confirmation`. Each new job snapshots the
opt-in; old jobs/chats are never retroactively authorized. Only after the validated
file receipt and exact native chat/prompt checks does the server authorize that
job's final Delete once. Agents wait for `cleanup_status=deleted` without calling
`extension_confirm_delete`. A restart invalidates unfinished cleanup rather than
replaying deletion. Saved files and hashes survive cleanup failure.

The post-delete Send readiness fix replaces the fixed 400 ms delay with a bounded
wait for a visible enabled native Send control, revalidating the live composer.
It ignores hidden retained controls. A new explicit image job can reuse an exact
matching unsent image draft without inserting twice; unrelated drafts, changed
text, attachments and running work remain protected. No failed job is auto-retried.

Live acceptance passed on 2026-10-16 after the owner reloaded the extension and
refreshed the paired second-account tab. Luna used real stdio MCP only: listed
the same four tools, checked account/pairing/online/policy and no active work,
then made one explicit `extension_image` request using the previously failed
production prompt. Job `142a894ac35d4cf286d0bfc57988f911` saved a 1448 × 1086 PNG,
SHA-256 `d376ab7c9d6b090718831ef68bc47ab23ce06e421af9e22f71d547de7fb4624d`.
The local file matched the receipt and visual inspection showed the requested
photorealistic citrus-and-spice flatlay. Automatic cleanup reached `deleted` with
single-use confirmation `consumed` for only that job's generated chat,
`/c/6ad1bced-6ec8-83ec-8484-757674570011`. No `extension_confirm_delete`, resolve,
browser-control action, or retry was used. Whether the reload blanked the prior
draft or the matching-draft path reused it was not observed and is not claimed.
Offline verification: 121 extension tests, 61 worker/client tests, and four skill
validators passed. This proves one live automatic save/delete flow, not batch
reliability, reference inputs, or Pro/High model selection.
Claude subsequently reported five additional sequential production jobs
(`f4bee24f`, `876604ca`, `04f48b56`, `935028f8`, `510e5439`) complete and
automatically deleted without confirmation calls; these are host-reported
follow-up results, separate from Luna's file/hash-verified acceptance above.
An isolated export of the exact staged release also passed all 121 Node tests,
61 Python tests and both exported skill validators, without unstaged changes.

Requested follow-up (not supported by 0.1.10): accept two actual local reference
images through MCP for the approved affiliate still pilot. Keep that change
separate from this cleanup release; it needs local-file/image validation and
native attachment handling before any production media is generated. Filenames
inside prompt text are not reference attachments.

### Popup and reconnect state

The popup now shows ready, busy, offline, incomplete-tab and result states, plus
**บันทึกภาพแล้ว รอยืนยันลบแชท** while the native Delete dialog awaits confirmation.
Ordinary reconnect hides the key form. A local-key rotation or explicitly choosing
**ลืมการจับคู่** still requires a new initial pairing; ordinary MCP restarts do not.
If the paired tab was closed, use **ตัวเลือก → เชื่อมแท็บนี้แทน — ใช้รหัสเดิม** on a
fresh normal chat. That reuses the saved key, but still requires confirming the
second account. It never silently selects another tab/account.

The 30-second alarm is restored when the worker starts. Reconnect can take one
alarm interval, and browser scheduling may delay it. A live server connection and
a ready image composer are separate states: MCP exposes `extension_online` and
`tab_ready`; version 0.1.7 accepts a new explicit job while the tab is not ready
so the extension can prepare it safely. Every actual send still rechecks the composer. Work interrupted by a server
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
It exposes `extension_status`, `extension_image`, `extension_confirm_delete`, and
`extension_resolve`.
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

Call `extension_status` first. When `account=second`, `paired=true` and `extension_online=true`, call
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
pairing to clear its stored key. The extension prepares a fresh empty native
image chat for the next explicitly requested image. Reference editing and batch
generation are not implemented.

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
