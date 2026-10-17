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

Keep exactly one owning worker running. The foreground command owns both the
loopback listener and stdio MCP. `--serve` runs only that listener, so closing
an agent does not stop the worker. Agent hosts use `--account second --connect`.
`--serve` and `--connect` cannot be combined. No tunnel, paid API, cookie capture,
or direct ChatGPT HTTP fallback is added.
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
# One owner. Use --serve when an OS user service should keep the listener up:
python -m chatgpt_api.extension_bridge --account second --serve
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

### Create/edit local image inputs (extension 0.1.11 candidate; offline only)

This candidate adds two explicit modes to the existing `extension_image` tool;
the other three MCP tools and cleanup policy remain unchanged. **Not deployed or
live-upload verified yet.** Do not treat the 0.1.10 live receipts above as evidence
that reference uploads or edits work. No new image/credit was used for this change.

```json
{
  "prompt": "Create a candid cafe photo using the supplied visual references.",
  "expected_model": "Create image",
  "mode": "create",
  "images": [
    {"path": "/absolute/goofy-full-body.png", "role": "reference", "description": "Goofy identity and harness"},
    {"path": "/absolute/cafe.png", "role": "reference", "description": "Shared cafe staging"}
  ]
}
```

- **CREATE:** `mode="create"` (default), prompt only or an ordered, variable-length
  list of reference images. Omit `images` for prompt-only generation.
- **EDIT:** `mode="edit"`, editing instructions in `prompt`, at least one image
  with `role="source"`, plus optional `role="reference"` guidance images. Sources
  may appear at any declared position; Bridge never silently reorders the list.
- Each item requires an absolute local `path` and a one-line `description`
  (1–200 characters). `role` defaults to `reference`; no extra fields are accepted.
  URLs, inline data/base64, directories, special files and symlink path components
  are rejected. Static PNG/JPEG/WebP content is decoded and checked, not trusted
  from its filename. Animated/multi-frame images are unsupported.
- **Bridge transport limits, not provider limits:** 8 MiB combined input bytes,
  8192px maximum edge, 40 million pixels per image, and 48 KiB combined metadata.
  There is no fixed two-image/tool count cap. The actual ChatGPT upload-count
  maximum is **not live verified**. A runtime input without `multiple` accepts
  only one image; unsupported native MIME/count/readiness fails before Send.

The worker snapshots validated inputs in the job's private directory (`0700`,
files `0600`). Original local paths and image bytes are absent from state/status;
state contains only ordered role/name/format/size/dimensions/hash metadata. The
original paired extension receives bytes once at claim time and checks hashes.
Extension storage and popup status never retain those input bytes. Snapshots
remain local alongside job records; chat deletion does not delete local files.
Claim/restart behavior remains at-most-once, with no automatic upload replay.

The content script constructs actual ordered `File` objects, uses the existing
native image file input, and dispatches input/change. Generated upload names are
numbered and the prompt explicitly maps each actual attachment to its source or
reference purpose. Filenames in prose are never used instead of uploads. Before
Send it requires all named preview cards, loaded thumbnails, native Remove
controls, exact attachment order and no upload progress/error, while rechecking
the prompt, account-bound tab, native image pill and idle chat. Unknown markup,
missing/reordered images or ambiguous inputs fail closed and preserve the unsent
draft; no clearing or retry is attempted.

**Live compatibility gate:** existing repository snapshots do not establish the
native file input or attachment-ready selectors. Mocked DOM tests prove byte/
order/readiness gating, not that ChatGPT currently exposes those exact markers.
The real native maximum and successful source/reference fidelity remain open.
Report any UI mismatch rather than substituting CUA, plain chat or a filename.

Deployment requires, at an idle point: restart the single owner worker from this
checkout (preserving its authorized auto-delete flag), reconnect MCP clients to
refresh the optional input schema, reload the same unpacked extension, and
refresh its already-paired `second` tab once. Do not create another owner, rotate
pairing, switch accounts or interrupt busy work. Require
`extension_status().input_capabilities.ordered_local_images=true` before sending
image inputs. A versioned heartbeat checks the content script as well as the
extension; stale receivers reject input jobs instead of silently dropping images.
The existing running 0.1.10 owner/content scripts were deliberately
left alone during this offline implementation.

This still uses native `Create image` on `second`. It does not expose or promise
GPT-6 Pro, GPT-6 Thinking extended/High, a highest-quality selector, identical
results to `main`, original-download resolution, batches, or saved @Characters.

#### No-Send upload preflight (same candidate; not live verified)

Use the same `extension_image` schema with `preflight_only=true` to prepare the
native image composer, attach actual ordered files and verify readiness, **without
inserting the prompt, looking up/clicking Send, generating, fetching an output or
deleting a chat**. Both CREATE and EDIT role validation still apply. This is a
new explicitly authorized diagnostic job, not a retry or generation request.
Require status `input_capabilities.preflight_only=true` (content protocol 2),
`tab_idle=true`, second/paired/online, and no running work or pending cleanup.
Older protocol 0/1 content cannot receive preflight jobs. An incomplete update
fails before delivery rather than allowing an old script to ignore the flag.

Successful preflight receipts have `state=complete`, `preflight_ready=true`,
`submitted=false`, `generated=false`, `cleanup_status=not_requested`, input
metadata and **no output image path**. Do not label them generated images or
production acceptance. The owned upload-only draft remains in the existing tab;
it is not silently cleared or sent later. Inspect it before further work; normal
jobs still refuse any preexisting attachments. On failure preserve the unsent
draft and diagnose the actual native mismatch, not an automatic retry.

Heartbeats now expose `tab_idle` and a short `tab_error` in MCP status, without
the user's draft text. Idle means no running work, unrelated text or attachments;
a completed conversation or missing image pill can be idle but not yet fresh.
Legacy clients that cannot report this diagnostic return `tab_idle=null`, never
an invented idle proof. No live preparation happens in ordinary status polling.

#### Receiver diagnostics (candidate 0.1.11)

`extension_status().extension_diagnostics` separates the running worker's
`worker_version` (read from `chrome.runtime.getManifest()`), `content_receiver`,
`content_protocol`, and `receiver_error`. An online extension alone proves only
the local heartbeat, not that its paired tab answered.

- `worker_version=null` / `content_receiver=unreported`: the running worker has
  not reported the new diagnostics; do not infer its version from files on disk.
- `available` with protocol 0/1: a receiver answered, but not with preflight
  protocol 2. `available` with protocol 2 and a `tab_error` means the new content
  script answered but the composer did not pass inspection.
- `tab_missing`, `wrong_origin`, `unavailable`, or `invalid_reply`: no usable
  inspection reply. Native exception text is never forwarded; `receiver_error`
  is restricted to `tab_missing`, `wrong_origin`, `no_receiver`, `port_closed`,
  `message_failed`, or `invalid_reply` (empty on success).

Diagnostics do not read login state, cookies, tokens, draft text or URLs; do not
change pairing or cleanup; and do not submit/prepare/upload anything. A configured
extension path proves configuration, not the loaded worker/content version.
To deploy these diagnostics: first restart the single **idle** owner from this
checkout with its existing account and cleanup flags, then use the already
installed extension popup's **ตัวเลือก → โหลดส่วนขยายรุ่นล่าสุด** once and
refresh the same paired `second` tab. Existing MCP `extension_status` needs no
new tool/schema. There is no MCP self-reload command in the pre-diagnostic worker;
do not fake a job or use browser control as a fallback. Until this deployment is
confirmed by the heartbeat, report diagnostics as unreported, not live acceptance.

Diagnostics verification (2026-10-16): 118 Python and 170 extension tests passed.
The first full run exposed a second worker test harness missing the new native
`getManifest()` fixture; that fixture and the finishing-heartbeat diagnostics
were corrected before the passing run. Tests cover legacy defaults, transient
diagnostics, strict version/enums, native-error sanitization, missing/wrong tabs,
old/new content replies and no job claim when inspection has no usable receiver.
The idle owner was restarted with the same `second` account and automatic saved
chat cleanup. Live MCP exposes the diagnostics fields; running extension/content
acceptance remains pending deployment of the new worker code. No image job,
preflight upload, Send, generation, account change or browser control was used.

#### Missing receiver repair (candidate 0.1.12)

The live diagnostic subsequently confirmed `worker_version=0.1.11`, paired and
online, but `content_receiver=unavailable`, `receiver_error=no_receiver`, and
protocol 0. This is an absent receiver in the existing paired tab, not an image
upload failure or an account/session authentication diagnosis. No preflight was
submitted through that failed gate.

0.1.12 adds native `scripting` permission and explicit host access only for
`https://chatgpt.com/*` (the same origin as the declared content script). When
the exact paired ChatGPT tab returns native `no_receiver`, and no local job is
active, the worker injects only the bundled `content.js`, then inspects once.
It does not reload/navigate the page, open tabs, read credentials, mutate drafts,
insert text, upload or click Send. A missing/redacted/wrong-origin tab, active
job, closed port, other message error or denied injection never triggers a
generation or unsafe fallback. Failed recovery is not repeated for that tab in
the same worker lifetime. Duplicate injection is guarded with native listener
registration checks, so an invalidated old marker cannot suppress a new listener.


#### Open tab with a redacted URL (extension 0.1.24)

Live MCP status on the deployed 0.1.23 worker reported `content_receiver=tab_missing` and `receiver_error=tab_missing` while the extension stayed online and paired. That means the saved tab id was gone. A different open ChatGPT tab does not answer that id, so the popup correctly said the paired tab was missing. 0.1.24 asks Chrome only for `https://chatgpt.com/*` tabs. Exactly one match replaces the saved tab id and keeps the existing client and local key. Zero or several matches are not chosen. The count is `extension_diagnostics.open_chatgpt_tabs` (0 through 20) and the popup names that count. This does not independently prove the tab is the second account; several open ChatGPT tabs still need the existing relink confirmation.

Chrome can hide the saved tab URL after an extension reload. That tab is still
open. 0.1.12 skipped receiver repair whenever the URL was missing, and the popup
title said the paired tab was absent. 0.1.24 injects bundled `content.js` once
into that same tab id when the only failure is `no_receiver` and no job is
active. The `https://chatgpt.com/*` host permission rejects any other origin.
It does not open a tab, switch accounts, or reuse a different ChatGPT tab.

MCP `extension_diagnostics.tab_present` separates those cases. `false` with
`receiver_error=tab_missing` means the saved tab is gone; use the popup option
that reconnects the current second-account tab with the saved local key.
`true` with `receiver_error=no_receiver` means the saved tab is open and the
listener has not answered. The popup title for that state is
"แท็บเปิดอยู่ แต่ตัวรับยังไม่ตอบ", not "ไม่พบแท็บที่เชื่อมไว้". Do not enter a
new pairing code for either case. A failed injection is not repeated in that
worker lifetime, and no queued image is claimed until a receiver answers.

#### Explicitly return an empty composer after preflight (0.1.12, protocol 3)

`extension_image` keeps the same dynamic create/edit input list and adds optional
`clear_preflight_uploads: bool = false`. It is valid as `true` only with
`preflight_only=true` and explicit owner approval. Protocol 3 adds
`input_capabilities.preflight_clear_uploads`; protocols 0/1/2 cannot receive a
clearing request, including a downgrade after enqueue. Default protocol-2
preflight still preserves its unsent uploads exactly as before.

The opted-in preflight first verifies all real ordered uploads, then clicks only
their verified native Remove controls. Before and between removals it rechecks
the job, editor, path, empty text, remaining exact attachment names/order, native
readiness and absence of foreign attachments. It never resets another input,
deletes source files/chats, navigates or clicks Send. Unknown/mutated UI stops
with remaining draft preserved; no silent retry or cleanup on failed readiness.
Success requires a strict `preflight_uploads_cleared=true` receipt in addition to
`preflight_ready=true`, `submitted=false`, `generated=false`, no output image and
no chat cleanup. Only that receipt means the composer is empty for a subsequent
explicit production request. Never infer this from `state=complete` alone.

Deployment: restart only the idle owner with its existing `second` account and
cleanup policy to activate protocol 3 and the optional schema field; other
clients use `--connect`. Then reload this same unpacked extension once to load
0.1.12 and its declared scripting/ChatGPT-site permissions. No pairing/setup,
account switch, or manual paired-tab refresh is required for receiver recovery.
Before the one authorized clearing preflight, require live version 0.1.12,
receiver `available`, protocol 3, `preflight_clear_uploads=true`, `tab_idle=true`
and no running work/pending cleanup. This documented repair is not evidence that
native upload selectors or the preflight have passed live.

0.1.12 offline verification (2026-10-16): 129 Python bridge/client/input tests,
193 content/worker tests and 14 popup tests passed (336 total); scoped diff checks
passed. Tests include native reinjection scope/permissions, stale listener guards,
0/1/3/>3 reference counts, protocol-3 downgrade safety, explicit clear receipts,
and strict preservation of all composer text (even an exact matching old prompt)
and foreign attachments before/between removals. The idle owner was restarted
with its original `second` account/pairing key and automatic saved-chat cleanup.
The remaining live deployment gate is activating extension 0.1.12 in Chrome,
then observing protocol 3 and executing one owner-authorized upload-only test.
No upload, Send, generation, quota, browser/CUA or commit/push was used for these
offline tests or server activation. The configured dedicated CDP endpoint
127.0.0.1:9222 was checked and was not listening; no Chrome was started/restarted.

Live activation follow-up (2026-10-16): after the owner activated the same
unpacked extension, MCP reported worker 0.1.12, receiver `available`, protocol 3,
all three input capabilities enabled, and `tab_idle=true`. Receiver recovery
therefore passed on the existing paired tab without browser/CUA control. Its
plain-chat/missing Create image state is not an upload failure: the guarded
`image-prepare` path selects native Create image before delivering a job. A fresh
stdio `--connect` client also listed exactly four MCP tools with the optional
`mode`, dynamic `images`, `preflight_only` and `clear_preflight_uploads` schema.
Use the literal virtualenv executable path: resolving its symlink to the system
Python caused a test-harness-only missing-Pillow import failure. These checks
alone are not live upload or generation acceptance.

The single live preflight subsequently created job
`8dee0add9b1e4541a5fb16cbc82135b0`. Native Create image preparation succeeded,
but upload selection failed closed: `Native image file input missing, ambiguous
or incompatible; nothing uploaded`. No text was inserted and no Send or
generation occurred. Do not repeat the same job or claim upload acceptance.
After an interrupted owner process was restored with the same account, pairing
and cleanup policy, extension 0.1.12 reconnected automatically and reported a
ready, idle tab without setup or browser control.

Candidate 0.1.13 adds read-only `extension_diagnostics.upload_dom` to distinguish
this selector failure. It reports only `editor_form` and bounded counts of file
inputs, form-local inputs, image-compatible/multiple/unrestricted inputs and
attachment cards. No HTML, text, filenames, input values, URLs, account details
or credentials are returned. Unknown/old receivers report null; malformed
diagnostics are rejected or normalized to null, not treated as readiness. This
does not change upload selection or submit another preflight. Live DOM counts
are required before choosing a selector fix.

0.1.13 verification: 138 Python bridge/client/input tests and 218 extension
content/worker/popup tests passed (356 total); scoped diff checks passed. The
running owner and Chrome extension have not been updated to this candidate.
An attempt to stop the idle owner for deployment was denied by the execution
safety reviewer because of the keep-running constraint; it was not retried or
bypassed. Owner approval for that narrow restart is required before activation.
The owner then explicitly approved that restart. After confirming all 41 saved
jobs terminal, no pending cleanup, an idle tab and the exact old owner command,
the same owner was replaced with unchanged account, pairing and cleanup policy.
The 0.1.13 server is active; Chrome activation and read-only live upload-DOM
diagnostics remain pending. No new image/preflight job was submitted.

Live 0.1.13 diagnostics then confirmed an available protocol-3 receiver, a ready
idle composer, four enabled file inputs in its form, three image-compatible
inputs, two multi-image inputs, one unrestricted input and no attachment cards.
This disproves the assumption that the form contains only one upload control;
the diagnostic alone does not identify every input's exact accept list.

Candidate 0.1.14 keeps the existing compatibility checks but, when multiple
controls match, accepts only a unique image-only picker instead of a generic
document picker. Multiple image-only controls still fail closed; no first-match
selection, unrestricted-input fallback or out-of-form upload was added. A
failure includes only compatible/image-only candidate counts. This selector
change still requires a new explicitly scoped preflight, not a generation retry.

The popup now displays the actually loaded manifest version even when MCP is
offline, separates connection state from the latest job result, shows the last
checked time and exposes technical job errors under a collapsed disclosure.
"โหลดโค้ดในเครื่องใหม่" replaces the misleading latest-version reload label:
the control reloads installed local files and does not download updates. Busy
preflight copy no longer claims that an image is being generated. Existing
pairing, account confirmation and active-job reload/deletion guards remain.
0.1.14 offline verification: 138 Python and 232 extension tests passed (370
total), including image-picker ambiguity, version visibility without MCP,
truthful failed/preflight copy and invalid timestamp handling. No live upload,
Send or image generation was performed for this candidate.
Popup visual QA used the actual popup files with mocked extension responses in
an isolated dedicated browser, never the paired ChatGPT tab. All 26 checks
passed: dark/light themes, visible runtime version, connected-plus-failed state,
offline state, local reload wording, accessible controls, no horizontal overflow
at 320px or 200% text, no console errors and no real network/actions. Screenshots
and the compact receipt are under `.opencode/visual-qa/gpt-bridge-popup/`.
These fixture images are UI evidence only, not live upload acceptance.

The owner's actual Chrome action-popup capture invalidated the 0.1.14 sizing
acceptance: the popup opened as a narrow column despite the fixed-size fixture
looking correct. `body { max-width:100vw }` allowed its width to depend on the
initial popup viewport rather than establish Chrome's intrinsic document size.
Candidate 0.1.15 gives the `html` root explicit width/min-width 380px and uses a
100%-width body with bounded 600px vertical scrolling. Header groups can wrap,
but the title/account do not break word by word. The earlier 320px mobile-page
expectation was removed: this is a Chrome action popup, not a responsive page.
All 233 extension tests pass, including a root-sizing regression assertion.
Preflight remains paused; no new upload job, Send or generation was performed.
The sizing regression was reproduced in the same isolated fixture: the prior
rules produced a 120px document at an initial 120px viewport, while 0.1.15 kept
the root/body at 380px. All 32 regression checks passed, including vertical
scrolling/control reachability and intact header groups at 200% text.
For the named native-popup gap, Chrome control was used only to open the
already-installed popup, inspect its actual layout and click its guarded local
reload control. The actual popup displayed version 0.1.15 and no longer formed
the narrow word-by-word column. No Chrome restart, ChatGPT submission or upload
was performed through browser control; subsequent upload testing stays in MCP.

The subsequent Luna MCP preflight was blocked by the approval reviewer before
process/job creation: general preflight authorization did not explicitly cover
the two private project images and their second-account ChatGPT destination.
No upload, job, Send or generation occurred, and no alternate route was tried.
Live upload acceptance remains pending specific owner authorization.

After explicit authorization for both named files and the second-account
destination, Luna ran exactly one MCP preflight, job
`b0fe914022014428b20978beaf5d555a`. Its gate passed (0.1.15, protocol 3,
paired/online/idle/ready, zero detected attachment cards). The job failed with
`Not submitted. Native uploads not verified ready; inspect the unsent draft.`
No readiness/clear receipt, Send, generation or output image occurred. No retry
or unverified cleanup was attempted.

A narrow read-only native UI inspection then showed both `input-001.png` and
`input-002.png`, each with its image and matching native Remove control, in the
empty Create image composer. Thus upload delivery did occur; the old
test-id-only attachment selector missed the current native cards. Its reported
zero cards and ready/idle status were not proof of an empty composer. Both
unsent attachments remain preserved. This is not successful live acceptance.

The pending 0.1.16 source repair discovers native cards by a thumbnail filename plus
the same filename on its Remove control, inside a single card, and shares that
discovery between readiness and diagnostics. Native Remove/progress controls
also block a supposedly empty composer when test ids are absent; unexpected
attachment controls fail closed. It does not adopt an old failed job's draft,
re-upload images, clear unknown attachments or claim an upload/clear receipt.
Luna's realistic no-test-id/React-cleared-FileList fixtures passed all 113 content
tests; the full extension suites passed 240 tests after updating the manifest
version assertion. The extension was reloaded through its existing guarded
local reload control only; the paired tab was not refreshed and its unsent
attachments were not manipulated. This reload is not a successful preflight.
Luna then verified 0.1.16 through real read-only MCP: receiver available, protocol
3, two attachment cards, tab_ready=false and tab_idle=false, with the expected
existing-attachments error. The false-empty status is fixed live.

#### Explicit cleanup of an inspected failed preflight (0.1.17, protocol 4)

The four tool names remain unchanged. After inspecting the original unsent
draft, and only with owner approval to remove those exact test attachments:

```python
extension_resolve(job_id="<original failed preflight>",
                  inspected_chatgpt=True, clear_preflight_uploads=True)
```

Require `input_capabilities.failed_preflight_cleanup=true`. This is one explicit
cleanup attempt of the same job, not a new upload or generation retry. It accepts
only the original paired client's failed upload-readiness preflight, originally
requested with clearing enabled, with no other work/cleanup pending. The prior
error is retained as `original_preflight_error`. Delivery contains metadata only,
never image bytes; it cannot call upload, prepare a new chat, insert text, Send,
fetch an output image or delete a chat. Restart interrupts rather than replays it.

The content receiver verifies a normal empty home composer, Create image mode,
no turns or running work, exact ordered unique filenames, loaded thumbnails and
matching native Remove controls, and rechecks the draft between removals. A
changed/extra/partial draft fails closed without a retry. Filenames are native
UI identity checks, not a recomputed server-side image hash: the operator must
inspect that this is the unchanged failed preflight before using the option.
Success retains `preflight_cleanup_only=true`, with `preflight_ready=true`,
`preflight_uploads_cleared=true`, `submitted=false`, `generated=false` and no
output image. This proves recovery of existing uploads, not a fresh upload run.
Independent review added two guards: an unpaired visible composer thumbnail
blocks readiness/removal even without a test id or Remove button, and recovery
rejects an older job if newer persisted work exists. Pydantic StrictBool prevents
numeric/string coercion from becoming inspection or cleanup approval.
Offline verification: 280 JavaScript tests and 161 Python extension tests pass.
The paired draft remains the source of live acceptance; these tests alone do not
prove the existing uploads were removed. The extension was reloaded through its
existing popup control, without refreshing ChatGPT or manipulating attachments.

Parallel workflow: one Luna performs bounded verification with a single actor
for the paired tab; another collects public primary-source reuse patterns without
touching accounts/runtime. The lead owns production fixes and safety decisions.
Research code is not installed/executed merely because a repository exists.

Preflight offline verification (2026-10-16): Luna xhigh passed 100 Python tests
and 162 extension tests (76 content, 86 worker/popup). Tests assert protocol-2
gating, actual ordered File uploads, no text insertion/Send lookup/click/output
fetch/deletion, strict readiness-only receipts, no generated-image receipt or
cleanup authorization, preserved unsent attachments and accurate popup labeling.
No live preflight, extension reload, owner restart or generation was performed.

Offline verification (2026-10-16): GPT-6 Luna xhigh ran 151 extension tests
(content/worker/popup), 90 Python bridge/client/input tests, and both bundled skill
validators, all passing. Tests cover prompt-only create, one and three inputs,
source-required edit, File byte/MIME/order identity, readiness failures, corrupt/
animated/oversized/unsafe inputs, metadata-only persistence, old receiver protocol
rejection, snapshot integrity and restart no-replay. A targeted regression found
that removing attachments during Send-control lookup could bypass the earlier
readiness check; a final synchronous composer/upload recheck now prevents Send.
These tests used only local fixtures and mocked DOM, no live ChatGPT generation,
Chrome/CUA, account changes, owner restart or extension reload. The candidate
is not a production/live-upload acceptance result.

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

### 0.1.18 asynchronous-removal repair (2026-10-16)

The first real cleanup-only call on the inspected failed preflight removed
`input-001.png`, then failed while React still displayed the old two-card set.
Live diagnostics subsequently showed one remaining card. This was a partial
cleanup, not an unchanged draft and not a successful preflight. No Send or
generation occurred.

The removal loop now keeps its old filename binding while the clicked card is
still present, waits for disappearance, then verifies the exact remaining set
before any next click. Explicit inspected recovery accepts only a nonempty
ordered suffix of the original filenames. Foreign images/text, changed composer,
and different chats still block cleanup. The server permits one explicit resume
of this exact historical transition error on the latest original-client job;
it preserves both errors and never re-uploads image bytes or automatically retries.
Protocol 4 remains wire-compatible; live acceptance requires runtime 0.1.18.

Live acceptance on `second`: Luna issued one inspected MCP resume on the same
original job `b0fe914022014428b20978beaf5d555a`. It completed with
`preflight_ready=true`, `preflight_uploads_cleared=true`, `submitted=false`,
`generated=false`, and the empty-composer receipt. The next native heartbeat
independently reported `attachment_cards=0`, `tab_ready=true`, `tab_idle=true`,
and no tab error (worker 0.1.18 / content protocol 4). Immediately after the
receipt, global diagnostics still reflected the previous one-card heartbeat;
wait for the next 30-second check rather than retrying cleanup. No new upload,
Send, generation, or chat deletion occurred during this recovery. Browser
control was used only to reload the installed extension; cleanup and acceptance
used MCP/extension. The two source files remain unchanged on disk.

Regression verification: 291 Node tests and 167 targeted Python tests pass,
including delayed native removal, foreign draft/file/path guards, exact suffix
recovery, same-client/latest-job gates and restart/no-replay behavior. This is
live upload-readiness/cleanup evidence, not a new reference-image generation or
visual-fidelity test.

An isolated HEAD-plus-release-files export also passed its full offline Python
suite: **466 passed, 3 skipped**, plus the same 291 Node tests. The first sandboxed
run denied six loopback-server fixtures; the exact full rerun with loopback
permission passed. Opt-in live-host tests stayed disabled. No unrelated dirty
direct-provider, GPT-6, OpenCode or packaging files were needed for this release.

Parallel reuse research inspected (not live-tested)
[BossDever/chatgpt-chrome-mcp-project](https://github.com/BossDever/chatgpt-chrome-mcp-project),
an adjacent CDP-based implementation. Its filename-associated DOM adapter and
post-removal polling support re-reading native state instead of assuming a click
is synchronous. This is not an extension/MCP transport match; no architecture
change, dependency or source copy was made (no declared repository license was
found). Source references:
[DOM adapter](https://github.com/BossDever/chatgpt-chrome-mcp-project/blob/main/src/chatgpt-dom-adapter.mjs),
[CDP client](https://github.com/BossDever/chatgpt-chrome-mcp-project/blob/main/src/cdp-client.mjs).

### 0.1.19 repeated-filename collision repair

A normal Shopee production request then exposed a separate real readiness
failure: native ChatGPT displayed `input-001(1).png` and `input-002(1).png`, while
Bridge expected its original exact names. Read-only accessibility inspection
confirmed both renamed cards and an empty unsent composer. The readiness failure
was therefore an exact-name mismatch, not proof that the upload was absent or a
reason to increase timeouts blindly. The 0.1.18 cleanup acceptance did not prove
normal reference generation.

New uploads now use `input-NNN-<job-id>.png` (or the actual JPG/WebP extension),
unique across jobs; snapshots, metadata and native upload all use that exact name.
Strict filename verification remains. Old queued metadata stays readable.

An operator may explicitly clear only a failed, latest, original-client normal
request with the exact `Not submitted. Native uploads not verified ready;`
error, after inspecting the unchanged empty draft:

```text
extension_resolve(job_id=..., inspected_chatgpt=true,
  clear_failed_uploads=true,
  native_upload_names=["input-001(1).png", "input-002(1).png"])
```

Names must be the original ordered names, optionally with a numeric duplicate
suffix before the extension. Metadata-only delivery checks the full exact native
set before Remove; no arbitrary subset, new upload, text, Send or generation.
The action is single-use. The original generation job remains **failed** with its
original error and `uploads_cleared=true`, never a false image-complete receipt.
It cannot be automatically retried. This is an explicit inspected compatibility
recovery, not a fuzzy matching policy for normal uploads or proof of native file
content hashes. The original local files remain intact.

Live inspected recovery on `second` (2026-10-16) cleared job
`a6b0f6eecde040c9a90bd10e3b6be9dd` through one standard stdio MCP
`extension_resolve` call, using the two observed `(1)` filenames above. The
receipt preserved `state=failed` and the original error, with
`uploads_cleared=true`, `submitted=false`, and `generated=false`. A subsequent
extension heartbeat confirmed zero attachment cards, `tab_ready=true`,
`tab_idle=true`, and no tab error on worker 0.1.19 / content protocol 4. No CUA
attachment removal, re-upload, Send, generation, or chat deletion was used.

An isolated export of the 0.1.19 release paths passed 486 Python tests
(3 skipped) and 297 Node extension tests. The review covered ordered-name
validation, same-client/latest-job gates, metadata-only cleanup delivery,
no-Send receipts, duplicate aliases, and restart/no-replay behavior.

The follow-up live preflight `7f2ee719fb9e4df09ccb0065e2d154cc` uploaded the
same two owner-authorized references via MCP with exact names
`input-001-7f2ee719fb9e4df09ccb0065e2d154cc.png` and
`input-002-7f2ee719fb9e4df09ccb0065e2d154cc.png`. It completed with
`preflight_ready=true`, `preflight_uploads_cleared=true`, `submitted=false`,
and `generated=false`. Upload readiness and removal were performed by the
extension, not CUA. This verifies the unique-name upload/preflight path, not
image generation or reference likeness. The next heartbeat again confirmed
zero attachment cards, ready/idle true, and no tab error on `second`.

## One bounded smoke test

### 0.1.20 assistant-output recovery

The first normal reference generation after 0.1.19 exposed a different result
collector bug: when the native UI omitted an assistant author-role attribute,
the old fallback counted large images in the entire Conversation region. That
region can include the uploaded references. It must not be treated as proof that
the provider returned multiple generated images.

The collector now scopes images to the assistant author-role element or the
body immediately following its native `ChatGPT said:` heading. It never counts
the full conversation as assistant output. Read-only heartbeat `result_dom`
reports only bounded counts, readiness booleans and the current `/c/...` path;
it does not expose image URLs, message text, cookies or tokens.

For an existing failed `Submission attempted. Multiple images returned;` job,
explicit recovery through the existing fourth MCP tool is:

```text
extension_resolve(job_id=..., inspected_chatgpt=true,
  recover_outputs=true, recovery_chat_path="/c/<exact-inspected-chat-uuid>")
```

It requires the latest failed job, original online 0.1.20 extension, no active
work, and the exact paired-tab path from diagnostics, with one completed user /
assistant turn and one to four scoped assistant images. It requeues the same job
once as metadata-only `collect_only`, never uploads, prepares another chat,
inserts text, clicks Send or deletes a chat. The content receiver also verifies
the exact single-turn original prompt and chat path. A restart or uncertainty
does not replay recovery.

All distinct displayed assistant sources are collected in DOM order, after the
whole ordered set is stable and generation has stopped. The limit is four
outputs and 25 MiB combined. Every image is validated before saving any image.
Receipts contain `outputs` with order, local path, dimensions, bytes and SHA-256,
plus `output_count`. Single-output receipts retain the legacy singular fields.
Multiple outputs are never silently reduced to one. Recovered results and all
multi-output results use `cleanup_status=preserved`, even under automatic chat
cleanup. An incomplete save preserves existing files and upstream chat; never
regenerate or overwrite mismatched local output files.

Source/unit tests alone do not establish the number of outputs in the failed
production chat. Live diagnostics and recovered-file receipts are required.
The isolated 0.1.20 release export passed 520 Python tests (3 skipped) and
318 Node extension tests. After owner reload, live `second` diagnostics on
2026-10-16 confirmed zero assistant author-role nodes, exactly one user heading
and one assistant heading, a found assistant body with **one assistant image**,
and **three conversation images**. Generation was no longer busy. This confirms
the old conversation fallback counted two uploaded references as outputs; the
provider did not return three generated images. No new generation is part of
recovery.

### 0.1.21 full rendered-prompt binding

The 0.1.20 live recovery stopped before fetching assets because the entire
native user-message wrapper did not equal the original full prompt. It did not
save an image or send another request. The collector now checks either the
whole body or a visible descendant's **complete rendered `innerText`** against
the complete normalized original prompt. It never uses a substring, regex,
hidden node, `textContent`, filename stripping, or a whole-conversation search.
The same exact chat path and single-turn guards still apply.

`prompt_binding` reports only `root_match`, `exact_matching_descendant_count`,
`expected_chars`, and `observed_chars`, including on a failed inspected
collection. No prompt text or DOM content is returned in diagnostics. This
allows native evidence to distinguish wrapper text from the authored prompt.

The same explicit `recover_outputs` action allows one compatibility resume
only for the exact old 0.1.20 prompt-mismatch failure without a binding receipt.
It requires 0.1.21, the original same-client/chat/latest-job gates, and a fresh
completed-output diagnostic. In that release, `output_recovery_resumed` prevented
another resume; the revision-gated 0.1.23 repair below supersedes that gate.
The receipt must include a successful
bounded prompt-binding diagnostic. No upload, Send, generation or deletion is
part of this resume.

The isolated 0.1.21 release export passed 535 Python tests (3 skipped) and
322 Node extension tests. After the owner's reload, the one live compatibility
resume failed safely before asset fetch: `root_match=false`, zero exact matching
descendants, 2688 expected and 2700 observed normalized characters. No output was
saved, no new upload/Send/generation/deletion occurred, and the original chat was
preserved. This does not establish which native UI label caused the difference.

### 0.1.22 read-only rendered-prompt diagnostics

`extension_status().extension_diagnostics.prompt_dom` adds bounded structural
evidence from the current user-message body. It reports character counts, whether
the body starts/ends with the literal native `Create image` label, and at most
eight visible elements whose entire rendered text equals that label. Each element
has only a fixed tag category and boolean semantic-attribute markers. No message
text, raw attributes, CSS classes, asset URLs, cookies or tokens are returned.
Legacy receivers report null. This heartbeat does not change the prompt matcher,
re-arm failed recovery, read image bytes, upload, Send, generate or delete.

Focused 0.1.22 checks passed: 197 Python bridge/client tests and 335 Node
content/worker/popup tests. The owner worker was restarted only after verifying
all 45 jobs terminal and no pending cleanup; second reconnected on 0.1.21 with
the same preserved chat. After reload, native evidence showed body length 2713,
stripped length 2700, a recognized 12-character image pill, and two nested label
spans. The recognized prompt-link span's parent is a paragraph. This supports
testing pill-aware paragraph matching; it does not identify the outer wrapper's
remaining text. No release commit/push had been made at that diagnostic checkpoint.

### 0.1.23 local regression before reload

The local fixture now reproduces a native pill inside the prompt paragraph and
extra text outside it. It must fail on the old matcher before the fix is applied.
Matching reads only rendered `innerText`, never form-control `.value`, hidden
`textContent`, or a substring. A candidate must equal the entire normalized
original prompt, or have exactly one recognized visible native pill with text
`Create image` at its leading edge, followed by that entire prompt. Arbitrary
wrapper text is not removed. Duplicate pills and changed prompts fail closed.

Explicit collect-only recovery may resume an exact prompt-mismatch failure only
with a strictly newer supported matcher revision. Diagnostic-only 0.1.22 shares
0.1.21's revision and does not unlock a retry. Revision 2 is bound to the claim
and must be echoed by the content-script receipt; a stale receiver cannot save
an output under the new matcher. Previous binding evidence is retained. The
same chat/client/latest-job/idle guards and no-Send/preserve-chat policy apply.

Reload policy: reproduce the live failure in a realistic local fixture, prove
old-code failure and fixed-code success, run the isolated offline release suite,
then request one candidate reload for native acceptance. Do not ask the owner to
reload for each speculative selector change, count test totals as proof of live
success, or push a recovery fix before native output saving is verified.

The isolated 0.1.23 release export passed 559 Python tests (3 skipped) and
341 Node tests. All 11 exported release paths matched the worktree after the
final regression tests. The owner was restarted only with all 45 jobs terminal
and no pending cleanup.

After the owner's 0.1.23 reload, one explicit revision-2 collection completed
through standard MCP and the paired second-account extension. Native binding
reported `root_match=false`, four exact matching rendered descendants, 2688
expected/2700 outer observed characters, and `matcher_revision=2`. This verifies
that excluding the recognized native pill inside the exact rendered prompt
scope resolves this production failure without discarding arbitrary wrapper text.

The existing job `b87ce0a366584347ad8c8fc78ffd6ace` saved one real PNG,
941×1672, 1,969,985 bytes, SHA-256
`fba15d15dcc8f5d0406afc8c38c5c62f53ff5dbf5d7b174ae00d47bf549a9e65`.
The lead independently checked file type, dimensions, hash and visible contents;
it is a new café kitten output, not either uploaded reference. The receipt is
`complete`, `collect_only=true`, `preserve_chat=true`, `cleanup_status=preserved`.
The original chat and both input files remain unchanged. No new upload, Send,
generation, retry, deletion, CUA or direct provider API was used in this acceptance.
This verifies recovery of the inspected existing image, not every future native
UI layout or original-download resolution.

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
image chat for the next explicitly requested image. Ordered reference uploads and
edit inputs are implemented; the latest live acceptance is preflight-only, not
proof of reference-edit generation quality. Batch generation is not implemented.

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
