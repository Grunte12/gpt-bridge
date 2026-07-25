---
project: GPT Bridge
updated: 2026-07-25
handoff-for: Continue GPT Bridge development without reviving removed products or weakening the local-only boundary.
---

# GPT Bridge repository refresh — definitive handoff

## Identity and intent

The public project is **GPT Bridge**. Its canonical command, Python distribution,
Compose project, Docker service/image, Console title, and Codex plugin are all
`gpt-bridge` / GPT Bridge.

It combines the local bridge API and useful worker workflow previously kept
separately. It is an independent local-first project, not an official service
and not a hosted product.

## Compatibility names that remain on purpose

- Python package/import: `chatgpt_api`
- Environment prefix: `CHATGPT_*`
- Some API route namespaces: `/v1/chatgpt/*`
- Executable aliases: `chatgpt-api`, `web-chat-bridge`, `wcbridge`
- Legacy migration environment/state paths where migration needs them

Do not present those as the public product name in new copy. New examples use
`gpt-bridge` and `YOUR_LOCAL_KEY`.

## Architecture

```text
visible user-controlled browser onboarding or manual local capture
  -> encrypted secrets/accounts store
  -> loopback API (127.0.0.1:8000)
  -> Console (127.0.0.1:8080), worker, Codex plugin, optional OpenCode client
  -> local outputs and authenticated artifact links
```

Docker Compose project name is `gpt-bridge`; running containers should be named
`gpt-bridge-gpt-bridge-1` and `gpt-bridge-bridge-console-1`.

## Security and policy boundary

- A unique `CHATGPT_API_KEY` is required. `scripts/setup-local.ps1` creates or
  rotates it in ignored `.env`; the known insecure `local-dev-key` is rejected.
- API and Console bind to loopback. There is no supported LAN/public deployment.
- Captures are credentials. Never commit, print, paste into issues, upload, or
  share `.env`, `secrets/`, cookies, tokens, raw requests, browser profiles, or
  artifact capability URLs.
- `gpt-bridge auth login` is consent-based and visible-browser-only. The user
  signs in, completes MFA/challenges, and sends a message. No stealth, password
  entry, profile attachment, CAPTCHA solving, challenge bypass, or secret output.
- No hosted service, account sharing, resale, multi-tenant operation, or
  provider-limit/safety-control evasion.

Read `DISCLAIMER.md`, `SECURITY.md`, and `PROVENANCE.md` before changing these
boundaries.

## Current product capabilities

- OpenAI-shaped loopback chat API with streaming/tool-call response shaping
- local account routing, model fallback, image generation/edit, vision/OCR,
  Deep Research operations, artifact storage/downloads, and local Console
- worker chat/image/research/report commands; durable local task threads;
  non-destructive import of old worker threads
- model-authored standalone HTML reports: no locked template; output is
  untrusted active content and must be inspected before opening
- optional OpenCode configuration and Codex worker plugin, neither captures
  credentials

## Removed scope

The former demo application, its Docker profile/service, source tree,
screenshots, and capture workflow were removed. Do not recreate or document it
unless the user explicitly requests a new scoped product.

## Local runbook

```powershell
.\scripts\setup-local.ps1

python -m pip install -e ".[dev]"
$env:CHATGPT_API_KEY = "YOUR_LOCAL_KEY"
$env:CHATGPT_BASE_URL = "http://127.0.0.1:8000/v1"
gpt-bridge worker doctor --json

# Optional visible user-controlled onboarding
gpt-bridge auth login --account main --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
```

Console: `http://127.0.0.1:8080`. API root returning `not_found` is expected;
use `/health` or `/v1/...`.

## Documentation map

- `README.md`: product overview and onboarding (English/Thai)
- `docs/CLI.md`: user command reference
- `docs/ACCOUNT_CAPTURE.md`: safe onboarding and manual fallback
- `docs/OPENAI_COMPATIBILITY.md`: local API contract
- `docs/ARCHITECTURE.md`: component/compatibility boundaries
- `docs/DOCKER.md`: local Docker operation
- `docs/RELEASE_CHECKLIST.md`: required verification
- `docs/MODEL_ALIAS_MAINTENANCE.md`: evidence standard for model aliases
- `integrations/opencode/README.md`: optional OpenCode consumer setup

## Verification status and next-agent checklist

After the repository-wide refresh on 2026-07-25, the complete suite passed:
compilation, **228 Python tests**, Console check/build, Node syntax checks for
both OpenCode launchers, plugin validation, Compose config, diff validation,
and a rebuilt Docker stack with authenticated health/worker-doctor and a
verified GPT Bridge Console page. Re-run `docs/RELEASE_CHECKLIST.md` after any
later change and before committing.

1. Read this file and `docs/HANDOFF.md` first.
2. Preserve local-only and visible-user-control boundaries.
3. Treat browser/session material as secret; do not ask for it in chat.
4. For public changes, update README, matching guide, Console strings,
   plugin/integration instructions, tests, and this handoff together.
