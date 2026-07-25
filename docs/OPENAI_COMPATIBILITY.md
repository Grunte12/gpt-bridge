# OpenAI-shaped local API

GPT Bridge exposes a local API shaped similarly to common OpenAI client
requests. It is not the official OpenAI API and is intended only for a
user-managed local installation.

## Connection

```text
base URL: http://127.0.0.1:8000/v1
API key:  the unique CHATGPT_API_KEY from .env
```

```powershell
curl http://127.0.0.1:8000/v1/models `
  -H "Authorization: Bearer YOUR_LOCAL_KEY"

curl http://127.0.0.1:8000/v1/chat/completions `
  -H "Authorization: Bearer YOUR_LOCAL_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"auto","messages":[{"role":"user","content":"Reply in one short sentence."}]}'
```

## Supported local routes

| Route | Purpose |
| --- | --- |
| `GET /health` | Liveness and local routing summary |
| `GET /v1/models` | Currently exposed aliases |
| `POST /v1/chat/completions` | Chat, streaming, and supported tool-call response shaping |
| `POST /v1/images/generations` | Image generation |
| `POST /v1/images/edits` | Image edit/composite |
| `POST /v1/chatgpt/vision` | OCR and image description |
| `GET /v1/chatgpt/operations/{id}` | Long-running operation status |
| `POST /v1/chatgpt/operations/{id}/cancel` | Best-effort cancellation |
| `GET /v1/chatgpt/files/{id}/{filename}` | Authenticated/capability-token artifact download |
| `GET /v1/chatgpt/admin/status` | Local operator status |

`/v1/chatgpt/*` is a compatibility route namespace; it is not a public product
name or an official endpoint.

## Models and routing

Use `auto` unless you have verified an explicit alias with your account:

```powershell
gpt-bridge worker doctor --json
```

The provider can reject a model even if you saw a similar name elsewhere. Model
availability, account limits, and provider behavior can change. Account pools
and failover are local routing tools, not a way to bypass account limits.

## Tool calls and artifacts

Clients execute tools. GPT Bridge returns compatible tool-call responses but
does not write files, run shell commands, or bypass a client's approval rules.

Image and research responses may include an artifact path and a local download
URL. Keep artifact URLs private: they are scoped to local files and are not
meant to be shared outside the machine.

## Boundaries

- Bind only to `127.0.0.1`; no LAN/public deployment is supported.
- Never send captures, cookies, or bearer values to another client/service.
- Do not treat API shape compatibility as provider affiliation or guaranteed
  compatibility with every OpenAI SDK feature.
