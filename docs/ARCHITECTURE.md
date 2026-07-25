# GPT Bridge architecture

GPT Bridge is a local-first, single-user application. Its public name and CLI
are `GPT Bridge` and `gpt-bridge`; several `chatgpt_*` names remain internal
compatibility contracts.

## Runtime topology

```text
User-controlled browser onboarding or manual local capture
  -> encrypted account store (secrets/accounts)
  -> GPT Bridge API on 127.0.0.1:8000
  -> Bridge Console on 127.0.0.1:8080
  -> local worker, Codex plugin, and optional OpenCode consumer
  -> local outputs and artifact metadata
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
| `chatgpt_api/worker/` and `threads.py` | Loopback client, durable local task threads, report/image/research commands, conservative stack control |
| `apps/bridge-console/` | Browser operator UI; never stores raw capture material in source or screenshots |
| `plugins/gpt-bridge/` | Codex worker skill; it may call an already-running worker but never handles browser credentials |

## Security decisions

- Docker publishes only loopback ports and requires a non-default bearer key.
- Captures are sensitive and encrypted in the local account store.
- Browser onboarding is visible, consent-based, and temporary-profile-only.
- Artifact downloads use per-file capability tokens; do not share their URLs.
- The worker refuses non-loopback base URLs.

## Compatibility decisions

`chatgpt_api` import paths, `CHATGPT_*` environment variables,
`/v1/chatgpt/*` routes, and legacy executable aliases are retained to avoid
breaking installed configurations. New user-facing text must say GPT Bridge.

## Change discipline

When changing a public workflow, update README, the relevant guide, Console
copy, plugin skill, integrations, and tests in one change. Validate with the
release checklist before publishing.
