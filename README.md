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

- `status`: readiness or an existing job receipt.
- `preflight`: verify ordered reference uploads without generation.
- `generate` / `edit`: submit once and retain the job ID. Edits need a source image.
- `wait` / `job`: follow that same job to saved local paths and cleanup receipts.
- `resolve`: recover inspected uncertain work, not blindly resubmit.
- `confirm_delete`: delete a specific saved chat after owner confirmation.

A timeout does not prove generation failed. Inspect the existing job first.
Automatic deletion is off unless explicitly enabled on the owning worker using
`--auto-delete-saved-chats`.

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
