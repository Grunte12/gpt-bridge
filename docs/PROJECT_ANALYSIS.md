# GPT Bridge — project map

## Purpose

GPT Bridge is a local-first, single-user bridge for a user-managed Web session.
It presents an OpenAI-shaped local API for compatible tools while keeping the
session, key, captures, generated artifacts, and operations on the user's own
machine.

## Main surfaces

| Surface | Location | Responsibility |
| --- | --- | --- |
| API and provider | `chatgpt_api/` | Account routing, API compatibility, encryption, artifacts, operations, model metadata |
| CLI | `chatgpt_api/cli.py` | `gpt-bridge` command, setup, local administration, server, worker, and onboarding |
| Worker | `chatgpt_api/worker/` | Loopback-only agent client, durable task threads, reports, research, image work, migration |
| Console | `apps/bridge-console/` | Local browser UI for health, captures, routing, storage, and API guidance |
| Docker | `Dockerfile`, `docker-compose.yml` | Loopback API/Console stack and persistent local volumes |
| Plugin | `plugins/gpt-bridge/` | Codex skill that may call an already-running local worker but never handles credentials |
| Integration | `integrations/opencode/` | Optional OpenCode consumer configuration |

## Names that are intentionally different

The public project is **GPT Bridge** and new commands use `gpt-bridge`.
`chatgpt_api` (Python import), `CHATGPT_*` (configuration), and `/v1/chatgpt/*`
(some compatibility routes) are retained internal contracts. Do not rename
them casually; doing so could break existing settings and clients.

## Data flow

```text
User-owned browser session
  -> encrypted local account store
  -> loopback GPT Bridge API (:8000)
  -> Console (:8080), worker, OpenCode-compatible clients
  -> local outputs/ and authenticated artifact links
```

Browser onboarding is always visible and user-controlled. The project never
prints or uploads captured values.

## Security model

- Default Docker ports bind to loopback.
- A unique bearer key is required; setup generates it in ignored `.env`.
- Captures are sensitive credentials and encrypted at rest.
- Artifact links use per-file capability tokens rather than exposing the API key
  to the Console.
- No supported public, hosted, or multi-user deployment exists.

## Source and release notes

The runtime does not require copied legacy reference source. See
`PROVENANCE.md`. Before release, follow `docs/RELEASE_CHECKLIST.md` and keep
all user-facing names and commands synchronized with `README.md`.
