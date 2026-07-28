# Docker: optional local API and Console

Docker is not required for `gpt-bridge worker`. The default direct worker calls
one selected account in-process and exits after each task. Use this stack only
when you need an always-on OpenAI-compatible HTTP endpoint, account routing, or
the Console.

The default Docker experience is intentionally small:

- `gpt-bridge` provides the local Bridge API on `127.0.0.1:8000`.
- `bridge-console` provides the local account/operator UI on
  `127.0.0.1:8080`.

Neither port is published to the LAN by default. The API is implementation
plumbing for the Console and optional HTTP clients, not a public service.

> ภาษาไทย: Docker default เปิดเฉพาะ API และ Console บนเครื่องนี้เท่านั้น
> ไม่เปิดให้เครื่องอื่นใน LAN เรียกได้

## First run

```powershell
.\scripts\setup-local.ps1
```

Open <http://127.0.0.1:8080>, enter the same key from `.env` in the Console
connection settings, then add or refresh your account capture under **Accounts**.

To create or rotate the key without starting Docker, use
`.\scripts\setup-local.ps1 -NoStart` or `-RotateKey -NoStart`.

Check the stack:

```powershell
$key = "YOUR_LOCAL_KEY"
$env:CHATGPT_API_KEY = $key
$env:CHATGPT_BASE_URL = "http://127.0.0.1:8000/v1"
curl http://127.0.0.1:8000/health -H "Authorization: Bearer $key"
curl http://127.0.0.1:8000/v1/models -H "Authorization: Bearer $key"
gpt-bridge worker doctor --json
```

## Persistence and updates

Docker mounts these local directories:

```text
./secrets/accounts/  # browser request captures; keep private and out of Git
./outputs/           # generated images, research files, and local metadata
```

Rebuilding containers keeps these folders. A rebuild does **not** refresh an
expired ChatGPT capture; update it in the Console instead.

```powershell
docker compose build gpt-bridge bridge-console
docker compose up -d gpt-bridge bridge-console
docker compose logs -f gpt-bridge
```

Stop the local product:

```powershell
docker compose stop gpt-bridge bridge-console
```

## Security notes

- Do not use `local-dev-key`; the server rejects it.
- Do not share `.env`, `secrets/`, browser captures, or generated artifact URLs.
- Artifact links use per-file capability tokens so the Console can display
  images/reports without exposing a global API key in the browser.
- This project does not provide a LAN/public deployment mode. Build a separate
  network and authentication design before exposing it outside your machine.
