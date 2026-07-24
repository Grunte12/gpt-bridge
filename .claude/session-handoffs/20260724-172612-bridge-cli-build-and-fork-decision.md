---
type: session-handoff
status: ready
project: chatgpt-api (with historical web-chat-bridge-cli and automation context)
source: chatgpt-api/.claude/session-handoffs/20260724-172612-bridge-cli-build-and-fork-decision.md
created: 2026-07-24T17:26:00+07:00
handoff-for: Continuing web-chat-bridge-cli development and the suphotP/chatgpt-api fork decision
---

# Session Handoff — web-chat-bridge-cli Build + chatgpt-api Fork Decision

## Active User Goal

Two threads, in order:
1. **Done, verified, stable**: build a standalone, publishable CLI (`web-chat-bridge-cli`) that lets any coding agent (Claude Code / Codex CLI / OpenCode CLI) call a user-managed ChatGPT bridge for chat/image generation as an external subprocess tool — never as a model-routing provider — with effectiveness features (presets, model fallback, thread compaction, HTML reports) layered on top.
2. **Decided, not yet started**: fork `suphotP/chatgpt-api` (the actual bridge server) to the user's own GitHub account and continue developing it, because upstream's maintainer has stopped active development (support window lapsed 2026-06-30) and the user wants to add support themselves if/when the bridge needs updating for newer ChatGPT models.

## The one non-negotiable boundary (read this before touching anything)

Account capture — copying a live browser request from the user's own logged-in ChatGPT session and pasting it into the bridge — stays **100% manual, browser-present, user-driven, forever**. This applies to `web-chat-bridge-cli` AND to any future fork/development of the bridge server itself. No tool, skill, script, or bridge-server code change may read, parse, paste, store, or replay session cookies/bearer tokens/browser requests, or automate ChatGPT login, on the user's behalf. Also permanently out of scope: auto-installing/auto-cloning the bridge, auto `--build`ing Docker images, retrying on auth/browser-challenge errors, exposing the bridge as a public/shared proxy, reselling access, or adding new detection-evasion sophistication beyond what upstream already had. This line was established early in the parent conversation (the user explicitly asked to "copy their logic/code" for the session-replay mechanism itself and it was declined) and has held through every subsequent build pass. Do not relitigate it; if a future request seems to erode it, pause and ask.

If continuing bridge-server (fork) development: keeping the model-alias list current with new legitimate OpenAI-shaped slugs is in scope (that's just tracking the API contract). Adding new session/browser automation is not, regardless of framing ("more automation the user doesn't have to do").

## Current Verified State

### `web-chat-bridge-cli` — v0.3.0, fully built and independently verified
- **Path**: `C:\Users\User\Documents\GitHub\web-chat-bridge-cli`
- **Git**: 4 clean commits, no `Co-Authored-By` trailers (user explicitly required solo authorship), working tree clean. **Not pushed to GitHub yet. Not published to npm yet.**
  1. `ae0c888` Initial v0.1.0
  2. `a7bdb29` README prose polish (Fable pass)
  3. `29c4d41` v0.2.0 — doctor/raw/stack commands, retry, error-code guidance, Thai setup skill
  4. `8c1f682` v0.3.0 — presets, model fallback, thread compaction, image `--enhance`, HTML reports
- **Tests**: 55/55 passing (`node --test`), real subprocess checks against embedded HTTP mocks, not just in-process assertions.
- **Independently re-verified by the lead (not just the build agent's own claim)** against a separate mock server written fresh each time: `status`, `chat` (with/without thread persistence), `doctor`, `raw`, `stack` (correct clean error when `WCBRIDGE_STACK_DIR` unset), concise-default system prompt, `--no-default-system` opt-out, preset precedence (explicit `--model` flag correctly overrides a `--preset`'s model), model fallback with `Note:` line, image `--enhance` transparently surfacing the expanded prompt, `report` (both a plain preset and the `research` preset's `download_url=` pointer-following path) — all confirmed correct.
- **Also verified against the REAL running suphotP/chatgpt-api bridge** (not just mocks): `status`, `chat` all returned real ChatGPT-backed responses.

### Package structure
```
bin/cli.mjs              status, chat, image, thread, doctor, raw, stack, report subcommands
lib/bridge-client.mjs    HTTP client: configureBridge, probeHealth, getUsage, checkHealth,
                         chatCompletion (transient-retry + model-fallback to auto@optimized on
                         chatgpt_model_limit/chatgpt_unsupported_model, never on auth/challenge),
                         imageGeneration, fetchText (raw non-JSON GET, for file downloads),
                         isRetryable, isAuthError, validateBridgeURL, isLoopbackAddress, shortId
lib/errors.mjs           explainError(): plain-English guidance per bridge error code; the
                         chatgpt_auth_or_browser_challenge guidance explicitly says "re-run
                         account capture yourself" — never implies auto-fix
lib/stack.mjs            docker compose wrapper: up/down/restart/logs/ps/status via execFile
                         (no shell). Reads WCBRIDGE_STACK_DIR (no default, clear error if unset).
                         up/restart default to the chatgpt-api service only (skip console+game
                         to save RAM) unless --full. Never passes --build. down never -v.
lib/presets.mjs          PRESETS: concise, structured, thai-content, brainstorm, plan, analysis
                         (all four heavy ones use model: gpt-5-5-thinking-max@optimized), and
                         research (model: chatgpt-deep-research). Written by a Fable pass —
                         genuinely specific system prompts, not generic filler.
lib/report-template.mjs  renderReportHTML({title, generatedAt, meta, sections}) — self-contained
                         HTML (dark mode via prefers-color-scheme, print styles, zero-JS TOC via
                         <details>, a11y skip-link). Written by the same Fable pass.
                         section.level is RELATIVE depth (1/2/3 -> h2/h3/h4; the report's own
                         title owns the single h1). section.html is TRUSTED/inlined verbatim —
                         callers must pre-escape body text themselves (markdown-report.mjs does).
lib/markdown-report.mjs  zero-dependency markdown -> {title, sections} converter feeding
                         report-template's exact contract; escapes all body text.
skills/claude/, skills/codex/, skills/opencode/    "external tool, not a provider" framing,
                         identical hard boundaries across all three
skills/setup-th/SKILL.md Thai-language guided setup walkthrough (clone+first-build framed as
                         done together/manually, `wcbridge stack up` for lightweight daily
                         starts, account-capture step unmissably bolded as 100% the user's own
                         hands, `wcbridge doctor` to verify)
test/unit.test.mjs, test/integration.test.mjs   55 tests total
README.md, package.json (v0.3.0), LICENSE (MIT, Copyright (c) 2026 Grunte12)
```

### Full current CLI surface
```
web-chat-bridge / wcbridge status [--json]
  chat --message "..." [--thread NAME] [--thread-window N=20] [--preset NAME]
       [--system "..."] [--no-default-system] [--model M] [--temperature N]
       [--max-tokens N] [--response-format T] [--json]
  image --prompt "..." [--enhance] [--out PATH] [--model M] [--size WxH]
        [--quality Q] [--style S] [--json]
  thread list|show NAME|clear NAME
  doctor [--json]
  raw <METHOD> </path> [--body '<json>']
  stack up|down|restart|logs|status [--full] [--follow] [--tail N] [--json]
  report --prompt "..." [--preset NAME] [--title "..."] [--out PATH] [--json]
```
Env vars: `BRIDGE_URL` (default `http://127.0.0.1:8000`), `BRIDGE_TOKEN`, `WCBRIDGE_DATA_DIR`
(default `~/.web-chat-bridge-cli`), `WCBRIDGE_STACK_DIR` (no default, required for `stack`).

### Consolidation already done in the `automation` repo (sibling project)
- **Path**: `C:\Users\User\Documents\GitHub\automation` (not a git repo — no commits needed/possible there)
- Removed the earlier, now-superseded duplicate: `scripts/bridge-cli.mjs`, `.claude/skills/chatgpt-bridge/` — grep-confirmed gone.
- Removed the `"bridge"` npm script from `package.json`.
- `content-studio/README.md` now points at the standalone `web-chat-bridge-cli` package instead of documenting a local duplicate.
- **`content-studio/lib/bridge.mjs` and `content-studio/lib/mock-bridge.mjs` were deliberately left untouched** — that's Affiliate Content Studio's own internal pipeline dependency (ideas→Thai-angles→scripts→shot-lists→image-prompts→images), a different purpose from the external CLI tool. Do not fold these together in future work.
- `npm run test:studio`: 176/176 passing, confirmed after cleanup.
- The original `.opencode/session-handoffs/20260713-affiliate-content-studio-chatgpt-bridge.md` handoff's stop conditions (BRIDGE_URL/TOKEN in `.env.example`, real bridge reachable, one real compatibility generation, mock regression gates passing, test-count reconciled) are now **all satisfied** — that handoff can be treated as closed/superseded by this one.

### Real bridge status (user's own machine, Windows, Docker)
- `suphotP/chatgpt-api` running via `docker compose up` (3 services: `chatgpt-api` on `127.0.0.1:8000`, `bridge-console` on `127.0.0.1:8080`, `character-game` on `127.0.0.1:3000`; Docker Desktop 29.2.0 confirmed present).
- One real ChatGPT **Plus** account captured and working (confirmed via `/v1/chatgpt/usage`: `plan_type: "plus"`, `plan_bucket: "paid"` — the local account alias name is unrelated to the detected plan, don't confuse the two).
- Real chat completions confirmed working end-to-end multiple times this session.
- Live `/v1/models` on this bridge, as of this session: `auto, gpt-5-5, gpt-5-5-thinking-standard, gpt-5-5-thinking-extended, gpt-5-5-thinking-max`, each also with `@optimized`/`@opencode` suffixes, plus `gpt-image-1`, `chatgpt-deep-research`. **No literal "5.6" or "Sol"-named model exists on this bridge yet.**

## The "GPT-5.6 Sol" question (why the fork idea came up)

The user's ChatGPT Web UI shows a model picker with an "Intelligence" tier (Instant/Medium/High) plus a separate "GPT-5.6 Sol" entry (vs. GPT-5.5, GPT-5.3, o3) — a model naming scheme from after the lead's training cutoff, genuinely can't be verified with certainty. Evidence gathered this session:
- The bridge's own live-captured account data (`/v1/chatgpt/usage`) shows `default_model_slug: "gpt-5-5"` and `observed_models: ["gpt-5-5"]` — i.e., the ChatGPT backend API itself is still returning `"gpt-5-5"` as the wire-level model identifier today, regardless of what the front-end UI displays as "GPT-5.6 Sol".
- Best-evidence working theory (not certain): "GPT-5.6 Sol" is OpenAI's current marketing/display name for the same backend model family the API still slugs as `gpt-5-5`, with "max" thinking-effort corresponding to the UI's "High" tier. If true, `gpt-5-5-thinking-max` (already what the heavy presets use) is already the ceiling this bridge can address — nothing is actually missing.
- Checked upstream `suphotP/chatgpt-api` directly: last commit `2026-06-28`, no GitHub Releases, zero commits/issues mention "5.6" or "Sol" anywhere. Maintainer's own stated support window (README/SUPPORT.md) was "through June 30, 2026" — already lapsed. MIT-licensed, maintainer explicitly says forking/continuing is fine, they've moved to a new personal project.
- **Nothing has actually broken yet.** The bridge still works correctly today because the backend slug (`gpt-5-5`) hasn't changed, whatever the UI calls it. The fork is motivated by "upstream won't fix it if/when it does break" more than an active bug right now.

## Decided, NOT yet executed

The user confirmed (after the lead explained the distinction in Thai between "improve our own CLI tool" vs "fork and co-maintain the actual bridge server") that they want **both**:
1. Fork `suphotP/chatgpt-api` to their own GitHub account (username: `Grunte12`, confirmed via `gh api user` earlier this session).
2. Actively continue developing it themselves going forward (not just a safety-net copy) — specifically to keep model-alias support current if/when the bridge's hardcoded model list needs updating for whatever underlies "GPT-5.6 Sol" or future model changes.

**Nothing has been forked or coded yet.** No `gh repo fork` has been run. No changes have been made to any copy of the bridge server's source.

## Exact paths

| Item | Path |
|---|---|
| `web-chat-bridge-cli` (canonical tool) | `C:\Users\User\Documents\GitHub\web-chat-bridge-cli` |
| `automation` (Studio + original integration) | `C:\Users\User\Documents\GitHub\automation` |
| Studio's own internal bridge client (do not touch/merge) | `automation/content-studio/lib/bridge.mjs` |
| Old, now-closed handoff | `automation/.opencode/session-handoffs/20260713-affiliate-content-studio-chatgpt-bridge.md` |
| Upstream bridge repo (to be forked) | `https://github.com/suphotP/chatgpt-api` |
| Upstream docs used this session | `docs/ACCOUNT_CAPTURE.md`, `docs/DOCKER.md`, `docs/CLI.md`, `docs/OPENAI_COMPATIBILITY.md` |
| GitHub username | `Grunte12` |
| npm package name confirmed available | `web-chat-bridge-cli` |

## Next exact actions (ordered)

1. **Confirm fork scope is still current** with the user at the start of the new session (a lot happened; a quick "still want to fork + actively maintain, right?" is worth a sanity check before starting, per the lead's own practice of not assuming stale confirmations carry forward).
2. **Fork the repo**: `gh repo fork suphotP/chatgpt-api --org Grunte12` or equivalent (confirm exact `gh` fork syntax — note: a previous `gh repo create ... --push` action in this same environment was blocked once by Claude Code's auto-mode permission classifier; forking may hit a similar gate and need explicit user re-approval, or the user may need to run it themselves).
3. **Scope what "continue developing" actually means concretely** before writing any bridge-server code — likely candidates: keep `/v1/models`' alias list current as OpenAI's model lineup changes, general bug fixes/dependency updates, anything else the user names. Do not assume scope beyond what's explicitly agreed — this is Python code implementing real session-replay against ChatGPT Web, a meaningfully different risk surface than the Node CLI, and deserves the same care about scope creep that the CLI work got throughout this whole conversation.
4. **Still outstanding, independent of the fork decision**: push `web-chat-bridge-cli` to GitHub (`gh repo create Grunte12/web-chat-bridge-cli --public --source=. --remote=origin --push` from that directory — was blocked once by the auto-mode classifier, needs retry/approval) and `npm publish` (explicitly the user's own action, never the lead's, per an earlier explicit decision in this conversation).

## Verification discipline to keep

Every agent-built deliverable this session was independently re-verified by the lead before being reported as done: re-run the test suite directly, and manually exercise new features against a **separate** mock server written fresh (not reusing a build agent's own test fixtures) before calling anything confirmed. Continue this pattern, especially for anything touching the bridge-server fork given the higher stakes.

## Multi-agent pattern used this session (for continuity)

- **Opus** (`model: "opus"`) for engineering/build passes — large, fully self-contained prompts (fresh agents have zero context), each independently re-verified afterward by the lead.
- **Fable** (`model: "fable"`) for content/design passes only (README prose, system-prompt wording, HTML template design) — explicitly scoped to not touch code/wiring.
- Sequential, not parallel, when one pass's output feeds the next (Fable's presets/template ran to completion before the Opus pass that wired them in, to avoid file-conflict/ordering issues).

## Stop condition for the still-open threads

- `web-chat-bridge-cli` pushed to GitHub and (whenever the user does it) published to npm.
- Fork of `suphotP/chatgpt-api` exists under `Grunte12` (if the user still wants it after the sanity-check in step 1 above).
- Any actual bridge-server code changes are scoped explicitly with the user first, keep the non-negotiable capture/login boundary intact, and are verified working the same way everything else this session was.

## Recommended new-session opening prompt

> Continue from the handoff at `web-chat-bridge-cli/.claude/session-handoffs/20260724-172612-bridge-cli-build-and-fork-decision.md`. Quick-confirm the fork-and-develop decision is still current, then fork `suphotP/chatgpt-api` to `Grunte12` and scope concretely what "continue developing" means before writing any bridge-server code. The account-capture boundary is non-negotiable and carries over unchanged to any bridge-server work.
