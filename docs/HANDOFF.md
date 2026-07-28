# GPT Bridge — implementation handoff

Updated: 2026-07-26

## Product in one sentence

GPT Bridge is an unofficial, local-first worker that lets one person use their
own Web session directly from agent tools, with an optional loopback
OpenAI-shaped API and Console.

## Current, verified state

- Canonical package, command, Compose project, service, and plugin name:
  `gpt-bridge` / **GPT Bridge**.
- Compatibility aliases remain: `chatgpt-api`, `web-chat-bridge`, and
  `wcbridge`. Do not use them in new docs or examples.
- The worker defaults to direct one-account execution and needs no Docker,
  daemon, local API key, or listening port.
- Optional Docker runs only `gpt-bridge` and `bridge-console`, bound to
  `127.0.0.1` on ports `8000` and `8080`.
- `gpt-bridge setup` is the primary consent-based one-shot local onboarding;
  `gpt-bridge auth login` remains the equivalent lifecycle command.
  It opens a random tokenized `127.0.0.1` page in the normal browser, never
  prints a capture, accepts one local paste, then closes. Private file import
  remains the fallback.
- The direct worker supports chat, local task threads, image work, research,
  and model-authored standalone HTML reports through one selected account.
  Chat and report default to verified alias `gpt-5-6-sol-high`.
- Captures are encrypted in the existing local account store. API access needs
  a unique `CHATGPT_API_KEY`; `local-dev-key` is rejected by the server.

## Public boundaries

- Keep this local and single-user. Do not add hosted operation, public/LAN
  exposure, account sharing, resale, multi-tenancy, stealth login, challenge
  solving, or provider-limit bypass.
- This is not affiliated with OpenAI and does not grant rights to OpenAI,
  ChatGPT, or GPT marks. See `DISCLAIMER.md`, `SECURITY.md`, and
  `PROVENANCE.md`.
- Internal compatibility names such as Python package `chatgpt_api`,
  `CHATGPT_*` environment variables, and `/v1/chatgpt/*` routes remain for
  interoperability. They are implementation/API compatibility names, not the
  public product name.

## Local runbook

```powershell
# Host development install
python -m pip install -e ".[dev]"

# Run one local setup page, then use the direct worker
gpt-bridge setup
gpt-bridge worker doctor --json

# Equivalent lifecycle command
gpt-bridge auth login --account main
```

Console: <http://127.0.0.1:8080>. API health: <http://127.0.0.1:8000/health>.

## Last verification

Completed on 2026-07-26 after the direct-worker update:

- `python -m compileall -q chatgpt_api`
- `python -m pytest -q` — **252 passed, 1 optional runtime test skipped**
- OpenCode runtime registration test — **1 passed**, exposing all five
  `gpt_bridge_*` tools from the installed tool module
- `bun run --cwd apps/bridge-console check` and `build`
- plugin validation for `plugins/gpt-bridge`
- `docker compose config --quiet`, rebuilt Docker stack, authenticated
  `/health`, and `gpt-bridge worker doctor --json`
- `git diff --check`

## Before the next change or release

1. Read `docs/RELEASE_CHECKLIST.md` and preserve the product/security boundary.
2. Add tests for behavior changes; do not use real captures in tests or logs.
3. Update README, CLI/API docs, Console wording, plugin skill, and integrations
   together when changing a user-facing command or workflow.
4. Re-run the full validation list in `docs/RELEASE_CHECKLIST.md`.
5. Never commit `.env`, `secrets/`, copied requests, browser profiles, or
   artifact capability URLs.

## ภาษาไทย

GPT Bridge คือเครื่องมือ local-first สำหรับใช้ Web session ของเจ้าของ account
ผ่าน API/Console/worker บนเครื่องตัวเองเท่านั้น คำสั่งหลักคือ `gpt-bridge` และ
Docker เปิดที่ `127.0.0.1` เท่านั้น ห้ามทำ public proxy, share account, ขาย access
หรือ bypass ข้อจำกัดของผู้ให้บริการ ก่อนแก้หรือ release ให้ทำตาม
`docs/RELEASE_CHECKLIST.md` และห้ามใส่ capture, cookie, token หรือ `.env` เข้า Git
