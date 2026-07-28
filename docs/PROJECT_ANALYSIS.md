# GPT Bridge — project map

## Purpose

GPT Bridge is a local-first, single-user worker for a user-managed Web session.
Agents use a direct one-account CLI by default; an OpenAI-shaped local API
remains optional for HTTP-compatible tools.

## Main surfaces

| Surface | Location | Responsibility |
| --- | --- | --- |
| API and provider | `chatgpt_api/` | Account routing, API compatibility, encryption, artifacts, operations, model metadata |
| CLI | `chatgpt_api/cli.py` | `gpt-bridge` command, setup, local administration, server, worker, and onboarding |
| Worker | `chatgpt_api/worker/` | Direct one-account transport, optional loopback client, durable task threads, reports, research, image work, migration |
| Console | `apps/bridge-console/` | Local browser UI for health, captures, routing, storage, and API guidance |
| Docker | `Dockerfile`, `docker-compose.yml` | Optional loopback API/Console stack and persistent local volumes |
| Skills | `plugins/gpt-bridge/` | Shared Codex/Claude instructions that invoke the direct worker CLI but never handle credentials |
| Integration | `chatgpt_api/assets/opencode/` | Native OpenCode tools that invoke the same direct worker CLI |

## Names that are intentionally different

The public project is **GPT Bridge** and new commands use `gpt-bridge`.
`chatgpt_api` (Python import), `CHATGPT_*` (configuration), and `/v1/chatgpt/*`
(some compatibility routes) are retained internal contracts. Do not rename
them casually; doing so could break existing settings and clients.

## Data flow

```text
User-owned browser session
  -> encrypted local account store
  -> direct worker / Codex / Claude / OpenCode tools
  -> local outputs

Optional:
  encrypted local account store
  -> loopback GPT Bridge API (:8000)
  -> Console (:8080) and OpenAI-compatible HTTP clients
```

Onboarding is always visible and user-controlled through a one-shot tokenized
loopback page in the normal browser. The project never prints or uploads
captured values.

## Security model

- Default Docker ports bind to loopback.
- Direct mode needs no bearer key. The optional HTTP server requires a unique
  bearer key stored outside version control.
- Captures are sensitive credentials and encrypted at rest.
- Artifact links use per-file capability tokens rather than exposing the API key
  to the Console.
- No supported public, hosted, or multi-user deployment exists.

## Source and release notes

The runtime does not require copied legacy reference source. See
`PROVENANCE.md`. Before release, follow `docs/RELEASE_CHECKLIST.md` and keep
all user-facing names and commands synchronized with `README.md`.
