---
name: "gpt-bridge-worker"
description: "Use the user's local GPT Bridge CLI for one-account chat, research, ChatGPT Image generation or editing—including transparent frontend PNG assets and image-based slide decks—persistent threads, or standalone HTML reports. Direct mode needs no Docker or daemon. Load task-specific references only on demand."
---

# GPT Bridge Worker

## Preflight

1. Run `command -v gpt-bridge` (or `Get-Command gpt-bridge` in PowerShell).
2. If missing, stop and tell the user to run
   `python scripts/install-agent-integrations.py`; never install automatically.
3. Run `gpt-bridge worker doctor --json`.
4. If the account is missing, ambiguous, or invalidated, tell the user to run
   `gpt-bridge setup` in their own terminal. Never onboard or select an account
   for them.

## Hard boundaries

- Never handle, print, or request capture contents, cookies, tokens, or keys.
- Never expose the local service publicly or use it to bypass provider limits,
  conceal automation, or resell access.
- Direct mode uses one selected account. Do not add routing or silently choose
  among captures.

## Route on demand

Use only the command and references required by the current request:

```powershell
# Chat or persistent task thread
gpt-bridge worker chat --message "..." --json
gpt-bridge worker chat --message "..." --thread planning --json

# Standalone model-authored HTML
gpt-bridge worker report --prompt "..." --out report.html --json

# New image, targeted edit/composite, or transparent frontend PNG
gpt-bridge worker image --prompt "..." --output-path <path> --brief
gpt-bridge worker edit --prompt "..." --input-image <path> --output-path <path> --brief
gpt-bridge worker image --prompt "..." --output-path <asset.png> --transparent --brief

# Deep Research
gpt-bridge worker research --prompt "..." --json
```

For every visual task, read `references/image-core.md`, exactly one matching
deliverable guide below, and only applicable risk guides:

- Frontend/web PNG asset: `references/frontend-asset.md`
- Photo: `references/realistic-photo.md`
- Illustration/concept: `references/illustration-concept.md`
- Infographic: `references/infographic.md`
- Technical diagram: `references/technical-diagram.md`
- Explanation visual: `references/explanation-visual.md`
- Product mockup: `references/product-mockup.md`
- UI mockup: `references/interface-mockup.md`
- Brand/marketing asset: `references/brand-marketing.md`
- Story/comic sequence: `references/story-sequence.md`
- Scientific visual: `references/scientific-visual.md`
- Spatial concept: `references/spatial-concept.md`
- Presentation deck: `references/presentation-deck.md`

Risk guides, only when triggered:

- Exact text/localization: `references/risks/exact-text-localization.md`
- Reference/edit consistency: `references/risks/reference-edit-consistency.md`
- Facts/data: `references/risks/factual-data.md`
- Batch/series: `references/risks/batch-series.md`
- Output/accessibility: `references/risks/output-accessibility.md`
- Failure/retry: `references/risks/failure-recovery.md`

Keep image iteration compact: use `--brief`, reuse one draft path, inspect only
the latest output, prefer `worker edit` for targeted changes, and never use
legacy `--enhance`. When an isolated worker/subagent exists, keep rejected
drafts there and return only the accepted path plus a short validation note.

Chat/report default to `gpt-5-6-sol-high`. Use HTTP transport only when the user
already runs a loopback gateway; otherwise keep direct mode.
