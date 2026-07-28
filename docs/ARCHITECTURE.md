# GPT Bridge architecture

GPT Bridge is a local-first, single-user application. Its public name and CLI
are `GPT Bridge` and `gpt-bridge`; several `chatgpt_*` names remain internal
compatibility contracts.

## Runtime topology

```text
User-controlled one-shot loopback setup page or private file import
  -> encrypted account store (stable per-user config directory)
  -> direct one-account worker and native Codex, Claude Code, and OpenCode adapters
  -> local outputs and artifact metadata

Optional:
  encrypted account store
  -> GPT Bridge API on 127.0.0.1:8000
  -> Bridge Console on 127.0.0.1:8080
```

No supported topology exposes the API to a LAN, the internet, multiple users,
or another person's account.

## Components

| Component | Responsibility |
| --- | --- |
| `chatgpt_api/api/openai_compat.py` | HTTP route orchestration, provider routing, streaming, and response shaping |
| `chatgpt_api/api/admin.py` | Local account/admin payloads, Console helpers, artifact administration, OpenCode configuration |
| `chatgpt_api/api/artifacts.py` | Artifact metadata, content handling, and secure download responses |
| `chatgpt_api/api/operations.py` | Long-running operation state and best-effort cancellation |
| `chatgpt_api/providers/chatgpt/` | Session capture parsing, encryption, account inspection, provider transport, and model metadata |
| `chatgpt_api/image_alpha.py` | Verifies native image alpha or safely converts a flat generated matte into a transparent frontend PNG |
| `chatgpt_api/worker/`, `web_sessions.py`, and `threads.py` | Direct one-account transport, compact signed-in Web conversation discovery/read/continuation, optional loopback client, durable local task threads, reports/image generation/reference edits/research, conservative stack control |
| `chatgpt_api/integration_installer.py` | Non-interactive host registration and non-destructive OpenCode configuration |
| `chatgpt_api/assets/opencode/` | Native OpenCode tools that invoke the direct worker CLI |
| `apps/bridge-console/` | Browser operator UI; never stores raw capture material in source or screenshots |
| `plugins/gpt-bridge/` | Shared worker skill, progressive image deliverable/risk guides, and presentation assembler copied directly into Codex, Claude, and OpenCode skill directories |
| `.claude/skills/gpt-bridge-worker/` | Project-scoped Claude Code development copy |

## Security decisions

- Direct mode creates no listening socket and uses exactly one selected account.
- Web conversation listing returns compact selection metadata; transcript
  export/continuation requires an explicit conversation id or signed-in Web URL.
- Optional Docker publishes only loopback ports and requires a non-default bearer key.
- Captures are sensitive and encrypted in the local account store.
- Setup binds an ephemeral `127.0.0.1` port, uses a random URL token, accepts
  one locally pasted capture, and exits without a daemon or automated browser.
- Artifact downloads use per-file capability tokens; do not share their URLs.
- HTTP worker mode refuses non-loopback base URLs.

## Compatibility decisions

`chatgpt_api` import paths, `CHATGPT_*` environment variables,
`/v1/chatgpt/*` routes, and legacy executable aliases are retained to avoid
breaking installed configurations. New user-facing text must say GPT Bridge.

## Change discipline

When changing a public workflow, update README, the relevant guide, Console
copy, plugin skill, integrations, and tests in one change. Validate with the
release checklist before publishing.
