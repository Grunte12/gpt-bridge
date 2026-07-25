# Local account onboarding and capture

An account session is sensitive credential material. Keep it on your own
machine; never commit, share, log, or paste it into an issue or chat.

## Preferred path: visible local browser

```powershell
gpt-bridge auth login --account main --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
```

Read the consent prompt. GPT Bridge opens an isolated visible browser window;
you sign in, complete MFA/challenges, and send one small message yourself. The
command does not print the session, uses a temporary browser profile, and asks
before saving through the encrypted local account store. The first run may
download bundled Chromium when a local Chrome channel is unavailable.

```powershell
gpt-bridge auth status --json
gpt-bridge auth logout --account main --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
```

## Manual fallback: copied request

Use this only when visible-browser onboarding is incompatible with your local
session.

1. In your own signed-in browser, open a conversation and send a small message.
2. In Network tools, find the `POST` conversation request.
3. Copy the complete request as cURL, or copy its URL, headers (including
   Authorization and Cookie), and JSON payload together.
4. Paste it only into the local Console **Accounts** page, or save through the
   CLI below.

```powershell
gpt-bridge admin account add --paste `
  --account main `
  --base-url http://127.0.0.1:8000/v1 `
  --api-key YOUR_LOCAL_KEY
```

For a prepared local file:

```powershell
gpt-bridge admin account add `
  --account main `
  --capture-file .\chatgpt-request.txt `
  --base-url http://127.0.0.1:8000/v1 `
  --api-key YOUR_LOCAL_KEY
```

GPT Bridge validates the local input and can live-check it after saving. A
capture can expire at any time; refresh it through the same user-controlled
flow when needed. Restarting Docker does not refresh a session.

## Local storage

```text
secrets/accounts/<account>/chatgpt-request.txt
secrets/accounts/<account>/settings.json
```

Docker maps that directory to `/data/secrets/accounts`. Stored captures are
encrypted by the existing account-store mechanism. On a shared machine, use a
passphrase-backed secret configuration where appropriate.

## Non-negotiable boundaries

- No password entry, stealth automation, normal-profile attachment, CAPTCHA
  solving, MFA bypass, or provider-control bypass.
- No public proxy, account sharing, resale, multi-tenant service, or LAN mode.
- Do not run copied cURL commands in a terminal or send raw captures to anyone.

## ภาษาไทย

วิธีหลักคือ `gpt-bridge auth login` ซึ่งเปิด browser แบบเห็นได้และแยก profile
ชั่วคราว ผู้ใช้ login/MFA/challenge เอง หากใช้ไม่ได้จึงค่อย copy request จาก browser
แล้ววางเฉพาะใน Console หรือ CLI บนเครื่องตัวเอง Capture เทียบเท่ารหัสผ่าน ห้ามแชร์
หรือ commit และ restart Docker ไม่ได้ทำให้ session กลับมาใช้ได้
