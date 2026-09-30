---
name: "gpt-bridge-worker"
description: "Use the user's local GPT Bridge CLI for one-account chat, research, existing ChatGPT Web conversation discovery/continuation/export, ChatGPT Image generation or editing—including transparent frontend PNG assets and image-based slide decks—vision/OCR, persistent local threads, or standalone HTML reports. Trigger when a user wants to bring a ChatGPT Web brainstorm into Codex, Claude Code, or OpenCode without replaying its full transcript. Direct mode needs no Docker or daemon. Load task-specific references only on demand."
---

# GPT Bridge Worker

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
