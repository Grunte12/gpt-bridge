---
name: gpt-bridge-worker
description: Generate and edit ChatGPT images through the paired GPT Bridge Chrome Extension MCP. Not a cookie-based chat or research client.
---

# GPT Bridge Extension

Discover the live GPT Bridge MCP schema through the configured gateway, if any.
Uses the ChatGPT login in the paired Chrome tab. No main/second account selection.
Never request cookies or ChatGPT tokens, run capture setup, import a session,
or launch a dedicated account profile.

1. Check `status`. If offline, ask the owner to open Chrome and the popup.
   For first installation, register Native Messaging with
   `gpt-bridge install-native --extension-id <actual GPT Bridge Chrome ID>`.
   Startup then connects automatically and opens its own ChatGPT work tab in
   the Extension's Chrome profile. No popup click is required. The owner only
   logs in normally if needed. Authorization transfers locally; do not ask them to
   run a terminal command or paste a pairing code. Chrome's Extension installation
   and permission confirmations remain owner actions. Never copy local secrets
   into agent chat or another agent's messages.
2. For one image, prefer `run(prompt, out_path, request_id)` when the live schema has it: it submits once,
   waits, saves to `out_path` and cleans up. On `status: running`, call `run` again with the same
   `request_id`. Read `cause`; use a new `request_id` only when `safe_to_retry` is true. Otherwise:
   Submit `generate` or `edit` once with explicit ordered reference roles.
   Edits require the source image. `preflight` tests uploads without generation.
3. Keep the job ID. Follow `wait` / `job` to saved paths and receipts.
   A healthy queue accepts more jobs; uncertain work must be inspected,
   not silently replaced or resubmitted after a timeout.
4. Inspect the saved image before claiming success. Report output and cleanup
   separately. Delete only the exact approved chat, or follow an explicitly
   configured owner cleanup policy.

Use only controls exposed by the live schema. Do not invent model/quality fields.
For upload or recovery problems, read
[recovery guidance](references/extension-image-recovery.md). Current schemas take
precedence over historical account labels or tool names in old incident notes.

CLI support: `gpt-bridge mcp`, `status --json`, `doctor --json`.
Legacy chat/research/report commands are not supported by this image Extension.
Do not claim those capabilities ran.
