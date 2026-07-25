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
- [ ] `gpt-bridge auth login` remains consent-based, visible-browser-only, and
      does not print captured values.
- [ ] Manual copied-request capture remains available when browser onboarding
      is incompatible with a user session.
- [ ] Account captures, artifacts, screenshots, and reports contain no secrets.

## Verification

```powershell
python -m compileall -q chatgpt_api
python -m pytest -q
git diff --check
# Optional, if you maintain the plugin with the Codex CLI's plugin-creator
# skill: run that skill's validate_plugin.py against ./plugins/gpt-bridge
docker compose config
docker compose up -d --build --remove-orphans gpt-bridge bridge-console
$env:CHATGPT_API_KEY = "YOUR_LOCAL_KEY"
$env:CHATGPT_BASE_URL = "http://127.0.0.1:8000/v1"
gpt-bridge worker doctor --json
```

Provider-facing chat, image, research, and login capture checks require the
release operator's own valid local account session. Do not automate or record
credentials in CI.
