---
name: "gpt-bridge-worker"
description: "Use the user's local GPT Bridge CLI for one-account chat, research, existing ChatGPT Web conversation discovery/continuation/export, ChatGPT Image generation or editing—including transparent frontend PNG assets and image-based slide decks—vision/OCR, persistent local threads, or standalone HTML reports. Trigger when a user wants to bring a ChatGPT Web brainstorm into Codex, Claude Code, or OpenCode without replaying its full transcript. Direct mode needs no Docker or daemon. Load task-specific references only on demand."
---

# GPT Bridge Worker

## Native image generation — extension 0.1.10

Prefer the `gpt-bridge-extension` MCP tools for the owner's image-generation
tasks. Test/use only `second`; never silently use `main` or direct HTTP.

1. Call `extension_status()`. Require `account=second`, `paired=true` and
   `extension_online=true`. `tab_ready=false` alone is not a blocker: a new
   explicit job prepares its native Create image chat automatically.
2. Call `extension_image(prompt=..., expected_model="Create image")` once.
3. Poll `extension_status(job_id=...)`. A saved image needs `state=complete`,
   a local path, dimensions and hash; inspect that file.
   - If `cleanup_policy=automatic_saved_chats`, the owner has opted into
     permanent deletion after validated saves. The script deletes only each
     newly Bridge-created image chat. Wait for `cleanup_status=deleted`;
     do not ask per image or call `extension_confirm_delete`.
   - Otherwise `confirmation_required` needs approval for that exact saved
     job/chat, then one `extension_confirm_delete(job_id=..., owner_confirmed=true)`.
   Pending cleanup blocks the next image. Cleanup failure never means regenerate
   the saved image or retry deletion. It cannot be re-armed in this version.
4. On failure/uncertainty, inspect existing work; never resend automatically.
   `extension_resolve` releases local work after inspection, not upstream
   generation or drafts. A new explicitly requested image may reuse an unsent
   native image draft only when its entire normalized prompt matches; it never
   clears an unrelated draft. The Send control is awaited, not clicked early.

One local worker owns the paired tab. With the owner's explicit standing
authorization, start that owner command with
`--account second --auto-delete-saved-chats`; do not enable it for another user
without their authorization. Other hosts use `--account second --connect`,
not another owning worker; the auto-delete flag belongs only on the owner.
Status reports the active policy. Default mode still requires per-job approval.
Policy applies only to jobs created while enabled, never old chats/jobs.

Keep the owner running. Pairing reconnects after restarts without tokens/cookies
or repeated setup. Restart invalidates pending cleanup; never replay it. The four
tool names/arguments are unchanged. An older host may still cache schema text;
read `cleanup_policy` from live status. Reload an old MCP host only at an idle
point, never by restarting a busy session.

No manual tab preparation is needed. Attachments, verification, running work,
changed prompts and unrelated drafts fail closed. Use browser control only for
initial setup/reload, a closed paired tab, login or necessary failure diagnosis,
not ordinary submission, receipt or deletion. This route does not yet support
reference edits/batches or guarantee Pro/High, highest quality, or original-download
resolution. Missing MCP tools are not a reason to use old direct image commands.

## Preflight

1. Run `command -v gpt-bridge` (or `Get-Command gpt-bridge` in PowerShell).
2. If missing, stop and tell the user to run
   `python scripts/install-agent-integrations.py`; never install automatically.
3. `worker tools` needs no account or network. Before any provider-backed
   command, run `gpt-bridge worker doctor --json`.
4. If the account is missing, ambiguous, or invalidated, tell the user to run
   `gpt-bridge setup` in their own terminal. Never onboard or select an account
   for them.

## Hard boundaries

- Never handle, print, or request capture contents, cookies, tokens, or keys.
- Never expose the local service publicly or use it to bypass provider limits,
  conceal automation, or resell access.
- Direct mode uses one selected account. Do not add routing or silently choose
  among captures.

## Discover and route on demand

When the route is obvious, use the matching core command below. For an
unfamiliar, visual, or mixed-purpose task, search first:

```powershell
gpt-bridge worker tools --query "<user task>" --json
```

Read exactly the references returned by that search. Never scan or preload the
whole `references/` directory. Running `worker tools --json` without a query
returns only a compact top-level capability list.

```powershell
# Chat or persistent task thread
gpt-bridge worker chat --message "..." --json
gpt-bridge worker chat --message "..." --level instant --json
gpt-bridge worker chat --message "..." --thread planning --json

# Existing ChatGPT Web conversations
gpt-bridge worker web list --query "title words" --json
gpt-bridge worker web show --conversation <id-or-url> --output context.md --json
gpt-bridge worker web pull --conversation <id-or-url> --output-path latest.png --json
gpt-bridge worker web send --conversation <id-or-url> --message "..." --json
gpt-bridge worker web delete --conversation <id-or-url> --yes --json

# Standalone model-authored HTML
gpt-bridge worker report --prompt "..." --out report.html --json

# New image, targeted edit/composite, or transparent frontend PNG
gpt-bridge worker image --prompt "..." --output-path <path> --brief
gpt-bridge worker image --prompt "..." --output-path <path> --count 4 --level instant --brief
gpt-bridge worker edit --prompt "..." --input-image <path> --output-path <path> --brief
gpt-bridge worker image --prompt "..." --output-path <asset.png> --transparent --brief
gpt-bridge worker image --prompt "..." --output-path <path> --cleanup-session --brief
gpt-bridge worker vision --mode describe --input-image <path> --json
gpt-bridge worker vision --mode custom --prompt "..." --input-image <path> --json

# Deep Research
gpt-bridge worker research --prompt "..." --json
```

When the task refers to an existing ChatGPT Web brainstorm, session, or chat,
read `references/web-sessions.md`. Prefer `web send` with an agent-authored
request for the exact artifact needed; this lets ChatGPT use its server-side
context while returning only the useful result. Use `web show --output` when
the coding agent needs source conversation material locally.

Keep image iteration compact: use `--brief`, reuse one draft path, inspect only
the latest output, prefer `worker edit` for targeted changes, and never use
legacy `--enhance`. For multiple variants, pass `--count N` (2-10) with one
`--output-path` stem. Use `--level instant` for cheap drafts (max 4), omit it
or pass `medium` for normal stills, and `--level high` for a hero/final.
The first request sends the full brief in a new ChatGPT conversation; later
variants continue that same session with a short follow-up so style stays
consistent and the brief is not repeated. Bridge writes `stem-01.png` ...
`stem-N.png`. Do not ask one prompt for N images. When an isolated worker/subagent exists, keep rejected
drafts there and return only the accepted path plus a short validation note.
For a clearly one-shot image or edit that is already saved locally and will not
be refined in ChatGPT Web, add `--cleanup-session`. Keep the session when the
user may iterate, when the purpose is ambiguous, or when recovery could matter.
Cleanup runs only after the local artifact and any transparency conversion
succeed.

OpenCode chat and vision default to `medium` (`gpt-5-5-thinking-standard`).
CLI `worker chat --level` sets that same tier; omit it and CLI chat/report
still default to `gpt-5-6-sol-high`. Image `--level` defaults to `medium`.
Use HTTP transport only when the user already runs a loopback gateway;
otherwise keep direct mode.
