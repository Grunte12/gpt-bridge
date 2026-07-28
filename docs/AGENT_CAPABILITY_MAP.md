# GPT Bridge agent capability map

This document is the complete structural inventory. It is repository
documentation, not agent prompt context. Coding agents discover only the skill
metadata, then its compact router, then task-specific references.

## Context-loading layers

1. **Host metadata** — Codex and Claude see the `gpt-bridge-worker` name and
   description for skill selection.
2. **Compact router** — `SKILL.md` loads only after the skill triggers.
3. **Local capability search** — `gpt-bridge worker tools --query "<task>"
   --json` returns a few matching routes and exact reference paths. It needs no
   account or network.
4. **On-demand references** — the agent reads only paths returned for the
   selected task.
5. **Deterministic scripts** — scripts execute without loading their source
   into model context.

## Host adapters

| Host | Installed surface | Native tool layer |
|---|---|---|
| Codex | `~/.codex/skills/gpt-bridge-worker/` or project `.agents/skills/` | Shell calls to `gpt-bridge worker`; no daemon |
| Claude Code | `~/.claude/skills/gpt-bridge-worker/` or project `.claude/skills/` | Shell calls to `gpt-bridge worker`; no daemon |
| OpenCode | Skill plus `gpt_bridge.ts` tools | Direct CLI-backed tools; optional HTTP provider |

Codex and Claude intentionally share one canonical skill source. They do not
need separate MCP servers or a marketplace.

## Agent-facing worker capabilities

| Capability | Main command | State/session behavior |
|---|---|---|
| Discovery | `worker tools [--query ...]` | Local and network-free |
| Health | `worker doctor` / `worker status` | Read-only local checks |
| Chat | `worker chat` | Temporary Web chat by default |
| Local task context | `worker chat --thread NAME`; `worker thread ...` | Versioned local JSON |
| Existing Web sessions | `worker web list/show/send/pull/delete` | Read-only except send/delete |
| HTML report | `worker report` | Saves standalone HTML |
| Image generation | `worker image` | Returns local output plus reusable Web session |
| Image edit/composite | `worker edit` | Accepts up to 10 ordered source images |
| Transparent asset | `worker image/edit --transparent` | Verifies alpha or safely removes a flat matte |
| One-shot cleanup | `worker image/edit --cleanup-session` | Soft-deletes only after local save succeeds |
| Deep Research | `worker research` | Long-running sourced research |
| Optional gateway | `worker --transport http`; `serve` | Loopback-only compatibility path |

## Web-session primitives

- `list` — compact title, ID, date, and Web URL metadata
- `show` — bounded current-branch read or Markdown/JSON export
- `send` — append an arbitrary agent-authored message using server-side context
- `pull` — download the latest or explicitly requested current-branch images
- `delete` — exact-ID, `--yes`-guarded soft-delete

## On-demand visual references

All visual routes start with `references/image-core.md`, followed by one
selected deliverable guide:

- `frontend-asset.md`
- `realistic-photo.md`
- `illustration-concept.md`
- `infographic.md`
- `technical-diagram.md`
- `explanation-visual.md`
- `product-mockup.md`
- `interface-mockup.md`
- `brand-marketing.md`
- `story-sequence.md`
- `scientific-visual.md`
- `spatial-concept.md`
- `presentation-deck.md`

Risk overlays load only when matched:

- exact text/localization
- reference/edit consistency
- facts/data
- batch/series consistency
- output/accessibility
- failure/retry

## Bundled deterministic scripts

- `scripts/images_to_pptx.py` — assemble accepted slide images into a flattened
  PowerPoint deck.
- `scripts/make_transparent.py` — verify alpha or remove a safe flat,
  edge-connected matte.

## Internal implementation layers

```text
Codex / Claude skill
    -> gpt-bridge worker CLI
        -> DirectWorkerClient (default, one account, no daemon)
            -> ChatGPTProvider
                -> ChatGPTWebTransport
                    -> signed-in ChatGPT Web

Optional compatibility:
OpenAI-compatible client
    -> loopback HTTP API
        -> same provider and transport
```

Supporting modules:

- `chatgpt_api/worker/capabilities.py` — compact discovery catalog
- `chatgpt_api/web_sessions.py` — normalization, bounded exports, asset lookup
- `chatgpt_api/threads.py` — local named task threads
- `chatgpt_api/image_alpha.py` — transparent-PNG verification
- `chatgpt_api/api/openai_compat.py` — optional loopback gateway
- `chatgpt_api/integration_installer.py` — Codex, Claude, and OpenCode adapters

## Cleanup rules

- Automatically clean only clearly one-shot image/edit sessions with an
  explicit local destination.
- Save and validate the artifact before cleanup.
- Preserve sessions after generation, download, or conversion failures.
- Preserve iterative sessions unless the user explicitly asks to delete them.
- For manual cleanup, select the exact conversation ID and require `--yes`.
