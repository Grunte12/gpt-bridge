---
name: "gpt-bridge"
description: "Use GPT Bridge for ChatGPT Web chat, research, conversation export, reports, vision, and native image generation or editing. For images, obey the project-selected route: Agent LinkHub/Extension when required, direct CLI only when explicitly selected. Never mix routes for one job. Load task-specific references only on demand."
---

# GPT Bridge Worker

## Native image route

Choose one image route from the current project's instructions and keep it for
the whole job. In Goofy & Memo, call the `gpt-bridge` provider only through
Agent LinkHub with account `second`. Do not bypass LinkHub by calling the direct
Extension MCP, direct HTTP, or the worker image/edit CLI, including for status
checks or recovery. If LinkHub lacks a capability, repair or diagnose that route
instead of silently switching routes. In another project that explicitly selects
the direct CLI image route, skip this LinkHub procedure and use the labeled
direct CLI guidance below.

1. Inspect the live LinkHub schema once. Before submitting, require
   `paired=true`, `extension_online=true`, queue depth `0`, and
   `next_action=submit_via_mcp`.
2. Call `generate(prompt, images)` or `edit(prompt, images)` once. `edit`
   requires the source image; `generate` images are ordered references.
3. Record the returned `job_id`. Follow `next_action` and recover that same job
   until its saved path, dimensions, hash, and cleanup outcome are known.
4. Inspect the saved artifact. A timeout, provider-discovery error, or uncertain
   cleanup state is not permission to submit again.

If `wait` returns `hub_unavailable` or `upstream_discovery_failed`, refresh the
LinkHub provider index once, call `status(job_id)`, then wait on the same job if
it is `claimed` or `remote_started`. `complete` plus a saved image path and hash
means the image succeeded; `cleanup_status=failed` affects chat cleanup, not the
saved artifact.

One local worker owns the paired tab. Other clients connect to that owner; do
not start a second owner. Use browser control only for initial setup/reload,
login, a closed paired tab, or necessary failure diagnosis. For HTTP 400 after
reload, a visibly empty composer reported as having attachments, upload/EXIF
failures, or a stuck job, read
[`references/extension-image-recovery.md`](references/extension-image-recovery.md)
before changing code or resubmitting.

Missing MCP tools are not a reason to use old direct image commands. Keep the
owner running, and reload MCP hosts only at an idle point.

## Direct CLI image quality — only when the project selects CLI

These controls do not apply to the LinkHub/Extension route. When the project
explicitly selects direct CLI and the user prioritizes final-image quality, use
`--level high` for prompt
fidelity and set the native model/effort explicitly. These are separate controls.
Read `worker doctor --live-models --json` once for the selected direct account
(or `account-models --account <alias> --json`) to discover current presets.
Default doctor model lists may be inferred from an older capture.

The GPT-6 High preset verified on 2026-10-13 is
`--model gpt-6-thinking --thinking-effort extended --level high`.
Use it only when that account's live picker confirms support. Do not invent
`highest`/`max` effort values, silently downgrade, or equate reasoning effort
with image-rendering quality. Generation still requires the user's task scope.
Correct forwarding is not a likeness guarantee; inspect the saved image.

## CLI preflight — non-LinkHub commands

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

# Direct CLI images — only when project instructions explicitly select this route
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

For the explicitly selected direct CLI image route, keep iteration compact: use
`--brief`, reuse one draft path, inspect only
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
