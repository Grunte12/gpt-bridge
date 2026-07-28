# GPT Bridge release checklist

## Product boundary

- [ ] The public name is **GPT Bridge**; `gpt-bridge` is the documented command.
- [ ] `chatgpt-api`, `web-chat-bridge`, and `wcbridge` are described only as
      compatibility aliases where relevant.
- [ ] The product is local-first: Docker ports bind to loopback and no public
      hosting, account sharing, resale, or provider-control bypass is claimed.
- [ ] The removed demo application is not referenced as a shipped component.

## Security and user experience

- [ ] `.env` contains a unique local key, never `local-dev-key`.
- [ ] `gpt-bridge auth login` remains consent-based, loopback-only, uses the
      normal browser, and does not print captured values.
- [ ] `gpt-bridge setup` uses a random tokenized one-shot page, completes
      encrypted save and live verification, then closes without Docker or a
      persistent local API.
- [ ] `gpt-bridge auth import` validates and encrypts a manual capture without
      requiring a server.
- [ ] The default account store is stable across working directories.
- [ ] Private file import remains available when the one-shot setup page is
      incompatible with a user session.
- [ ] Account captures, artifacts, screenshots, and reports contain no secrets.

## Verification

```powershell
python -m compileall -q chatgpt_api
python -m pytest -q
GPT_BRIDGE_RUN_OPENCODE_RUNTIME_TESTS=1 python -m pytest -q tests/test_opencode_runtime.py
git diff --check
gpt-bridge worker doctor --json
python scripts/install-agent-integrations.py --dry-run --json
gpt-bridge integrations install --dry-run --json
docker compose config
docker compose up -d --build --remove-orphans gpt-bridge bridge-console
$env:CHATGPT_API_KEY = "YOUR_LOCAL_KEY"
$env:CHATGPT_BASE_URL = "http://127.0.0.1:8000/v1"
gpt-bridge worker --transport http doctor --json
```

Provider-facing chat, image, research, and login capture checks require the
release operator's own valid local account session. Do not automate or record
credentials in CI.
