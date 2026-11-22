# GPT Bridge

Local MCP tools for ChatGPT image generation and editing through a Chrome Extension.
Uses the account already logged in to the paired Chrome tab. No ChatGPT cookies,
access tokens, account aliases, or dedicated browser profiles.

## Install

Requires Python 3.11+, Chrome, a logged-in ChatGPT account with image generation,
and an MCP client such as Codex, Claude Code, or Cursor.

From this checkout:

```sh
python -m pip install -e '.[mcp]'
```

1. Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**,
   and select `extensions/chatgpt-image`.
2. Add this local MCP configuration to your agent. Use an absolute command path
   if the agent cannot find it on PATH:

```json
{"mcpServers":{"gpt-bridge":{"command":"gpt-bridge","args":["mcp"]}}}
```

3. Ask your agent to register the local Chrome connector using the GPT Bridge
   extension ID shown in `chrome://extensions`:
   `gpt-bridge install-native --extension-id <GPT_BRIDGE_EXTENSION_ID>`.
   This is agent installation work, not a command the end user needs to run.
4. Start/reconnect MCP. The Extension automatically connects and opens one
   background ChatGPT work tab in its Chrome profile. No popup click, tab
   confirmation, account selector, or pairing code is required. Log in normally
   if that Chrome profile is not already logged in.
5. Ask your agent to check `status`, then generate or edit.

The pairing code protects the local worker. It is **not** a ChatGPT token.
Do not share it in chat, logs, or public configuration. Do not switch accounts
in the paired tab during a job.

Auto-connect leaves existing user tabs alone, reuses its own work tab after
failure, and will not replace an active/uncertain queue. Explicit Disconnect
disables auto-connect until manually connected again. The popup's manual tab
connection remains a repair option, not the normal startup path. Chrome login
is reused; Bridge does not independently verify the account's email or plan.
When several Chrome profiles install the Extension, only one owns the worker;
other profiles will not steal that pairing automatically. Local secret rotation
refreshes authorization while preserving the same tab, client, and job IDs.

## Commands

```sh
gpt-bridge mcp                # Start MCP; reuse a healthy existing local owner
gpt-bridge status --json      # Connection, queue, next action
gpt-bridge doctor --json      # Local connection diagnostic
gpt-bridge install-native --extension-id <ID>  # Agent-only one-time connector registration
```

For several agent hosts, keep one owner running with `gpt-bridge mcp --serve`;
clients use `gpt-bridge mcp --connect`. All share one FIFO queue.
The queue accepts up to 10 unfinished jobs and runs one at a time. Each agent
must retain its own returned `job_id` and use `wait` / `job`, not resubmit while
waiting. Status reports waiting and in-flight counts. Additional tabs do not
provide separate account quota. See [concurrency evaluation](docs/WORKER-POOL-EVAL.md).
The worker and Chrome must remain running. No cloud service is needed.
Chrome still requires the user to approve adding an unpacked Extension and any
new permissions. Installing the local connector does not silently install an
Extension into an existing Chrome profile. A legacy manual `pairing` command
remains only for diagnostic compatibility, not normal onboarding.
The current worker uses a Unix file lock; native Windows support is not verified.

## Workflow

- `run`: one image in one call (see below). Prefer this.
- `status`: readiness or an existing job receipt.
- `preflight`: verify ordered reference uploads without generation.
- `generate` / `edit`: submit once and retain the job ID. Edits need a source image.
- `wait` / `job`: follow that same job to saved local paths and cleanup receipts.
- `resolve`: recover inspected uncertain work, not blindly resubmit.
- `confirm_delete`: delete a specific saved chat after owner confirmation.

A timeout does not prove generation failed. Inspect the existing job first.
Automatic deletion is off unless explicitly enabled on the owning worker using
`--auto-delete-saved-chats`.

### One-call workflow: `run`

`run(prompt, out_path, request_id, images=None, mode="create", cleanup="delete_on_success", timeout_seconds=300)`
does the whole chain in code: durable enqueue, wait, collect, copy the saved image to `out_path`
(absolute path; an existing file is replaced atomically), chat cleanup and recovery. It returns one receipt:
`{status, out_path, width, height, sha256, job_id, chat_path, cleanup_status, error, cause, safe_to_retry}`.

- `status` is `done`, `failed` or `running`. `running` means the time bound ended first: call `run` again
  with the same `request_id`. The same ID always continues the same job and never submits twice.
- `cleanup="keep"` never touches the chat. `cleanup_status` is `deleted`, `preserved` or `kept`.
  A failed delete keeps the chat (`preserved`, `delete_failed: true`) and never blocks the queue.
- `safe_to_retry: true` means a new `request_id` cannot duplicate work already sent to ChatGPT.

| `cause` | Meaning |
|---|---|
| `ok` | Image saved; cleanup as requested. |
| `false_stall_recovered` | The worker tab stopped showing progress; one fresh visible reload of the same chat found the image. |
| `timeout_output_recovered` | The job timed out, but the exact chat held a finished image; it was collected, not regenerated. |
| `delete_failed_preserved` | Image saved; the chat could not be deleted and is kept. |
| `multiple_outputs_preserved` | Several images returned; the first is at `out_path`, all are listed in `outputs`, chat kept. |
| `awaiting_worker`, `still_running`, or a composer hold | Not finished inside the time bound (`status: running`). |
| `chatgpt_no_image` | ChatGPT answered without an image (refusal or error) and the one replacement also failed or was not allowed. |
| `generation_timeout` | No image after the timeout and a fresh look at the chat. |
| `stalled_hidden_tab` | Timeout while the page stayed hidden even after Chrome was focused; chat kept unchecked, nothing regenerated. |
| `verification_required` | ChatGPT asks the owner to verify; a human must act once. |
| `not_submitted` | Nothing reached ChatGPT. |
| `delivery_unknown`, `interrupted_unknown`, `output_unreadable`, `unexpected_outputs`, `recovery_failed`, `failed_unknown` | Sent or possibly sent; do not retry blindly. |
| `extension_offline`, `extension_version_mismatch`, `queue_full`, `cleanup_in_progress`, `request_id_conflict`, `invalid_out_path`, `invalid_request`, `not_accepted`, `save_failed` | Refused before submission, or the copy to `out_path` failed (`image_path` still has the file). |
| `output_expired` | A resume after the bridge copy expired, and `out_path` does not hold the image. Never re-run; use the first copy. |

Stall handling (extension 0.1.46): every result check first loads the gallery eagerly and scrolls it into view.
After 150 s without an image, and again before any timeout is recorded, the worker activates the job tab in
its own window and reloads the exact bound chat once. Chrome is focused only if the page still reports hidden
10 s later. The user's previous tab is restored afterwards. `status` and the other tools are unchanged.

### Output retention

The bridge is a pass-through. The caller keeps the image in its own project; the
job folder copy is temporary.

| What | When it is deleted | Kept |
|---|---|---|
| `input-*` pinned uploads | When the job ends (`complete`, `failed`, `interrupted`) | names, sha256, bytes in `state.json` |
| `image*.png/jpg/webp` outputs | 7 days after `completed_at` | `state.json` with sha256, dimensions, chat path |
| Never-sent queued request | 7 days after acceptance: becomes `interrupted`, nothing reached ChatGPT | `state.json` |
| `worker/images` (direct worker default folder) | Files older than 7 days | other files and subfolders |

- Set the age on the owning worker: `--output-ttl-days N`, or `GPT_BRIDGE_OUTPUT_TTL_DAYS=N`.
  `0` keeps outputs forever. `--connect` cannot set it.
- The sweep runs when the owner starts and after every completed image. It never
  touches a job in progress, a job whose chat cleanup is still open, or a job of a running batch.
- `state.json` is never deleted, so `request_id`, `payload_hash` and job lookups keep no-replay working.
- Receipts for a finished image add `output_status: available`, `output_expires_at` (UTC) and
  `output_note`. Copy `image_path` into your project before that time (`run` does it for you).
- After expiry, `job`, `wait` and `status` return `output_status: expired`, `image_path: null`
  and the original `sha256`. `run` with the same `request_id` returns `done` if `out_path`
  still holds those bytes, else `output_expired`. It never submits again.

## Agent guidance and migration

Install `plugins/gpt-bridge/skills/gpt-bridge-worker`, or run:

```sh
python scripts/install-agent-integrations.py --target codex
# Alternatively: --target claude
```

The supported route is Extension MCP. Capture-based chat, research, report,
account-pool and HTTP-provider implementations in the source are legacy only.
`setup`, `auth login`, and cookie import are not public CLI commands.
Existing captures are not deleted or used by the Extension.

Existing queues and local pairing data are preserved. A historical folder named
`second` is only a storage namespace, not an account selector.

If offline, open Chrome and check the popup. If the paired tab is lost, reconnect
the desired ChatGPT tab there. Reload updated Extension files only when idle.
Old setup advice means the installed agent skill needs updating.

UI changes, login expiry, provider limits and generation availability can
interrupt work. No login-challenge or provider-limit bypass is provided.
See [Security](SECURITY.md), [Disclaimer](DISCLAIMER.md), and [License](LICENSE).

### Durable image batches

The worker owner must explicitly allow each run with `--batch-run-root /absolute/run`
(default: none). Each run must contain `prompts.json`, `generation_log.tsv`, `raw/`
and `receipts/`. `batch_start` accepts a batch ID, ordered `{scenario_id, prompt, prompt_sha256}`
items, and existing absolute `destination` and `attempts` directories. It writes
an immutable batch receipt, reserves one prompt at a time in the existing FIFO,
and creates `<scenario_id>-attempt.json` before enqueue. Completed images are
copied with exclusive creation and SHA-256 verification. Use `batch_status` for
per-item job IDs and progress. Identical starts return the existing batch; changed
inputs under the same ID are rejected. The worker checks each prompt against the allowed registry and rejects IDs in
either the generation log or attempt markers, including uncertain attempts. Audit
the full source ledger and intended set independently immediately before starting.
A restart, failed/uncertain job, unavailable tab, or copy error stops the batch;
inspect the existing receipt and never resend uncertain work. Batch timeouts
preserve their chat and do not create replacements. Batch completion is not a
guarantee that every remote request finished after a crash.

### Durable waiting requests (local patch; activate only when the owner is idle)

`enqueue(request_id, prompt, images=None, mode="create")` accepts one immutable
request through MCP and returns a durable `job_id`, `request_id`, `payload_hash`
and FIFO sequence. During a running batch its state is `waiting_for_batch` and
`blocked_by_batch` identifies the owner. This is acceptance, not submission to
ChatGPT. Read `job(job_id)` or `wait(job_id)`; do not also call `generate`.
For one image tied to an order, use the caller's order reference unchanged as
`request_id`. If `user_message` is returned, tell the user what is blocking that
specific job and how to proceed. A known composer hold returns immediately
from `wait` and is **not** a timeout or a new submission. Preserve any existing draft.

Ordered reference images are validated and copied into the job directory before
the receipt is returned. Repeating the same ID and arguments returns the original
snapshot, even if source files have since changed or disappeared. Changed prompt,
mode, image path, role or description under that ID is rejected. Use a new ID for
an intentionally new request; never use a new ID to retry uncertain delivery.
The payload hash includes prompt, mode, ordered image roles/descriptions and
content hashes, not the mutable source paths.

Waiting requests do not interleave with a batch. They are released only after the
blocking batch is durably complete and tab cleanup/uncertainty gates are clear.
A stopped or missing batch remains blocked for inspection. Never restart an active
batch to deploy this patch. Never-delivered enqueue requests survive an owner
restart; previously delivered work retains the existing no-replay policy.
The existing queue bound applies; a full queue rejects before acceptance.
