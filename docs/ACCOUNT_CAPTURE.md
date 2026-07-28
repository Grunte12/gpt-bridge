# Local account onboarding and capture

An account session is sensitive credential material. Keep it on your own
machine; never commit, share, log, or paste it into an issue or chat.

## Preferred path: one-shot local setup page

```powershell
gpt-bridge setup
```

Read the consent prompt. GPT Bridge opens a random tokenized page on
`127.0.0.1` in your normal browser. Use your existing signed-in ChatGPT tab,
send one small message, copy its conversation request as cURL from Network
tools, paste it into the large local form, and click Save. The command does not
print or upload the session; it saves through the encrypted account store,
verifies the session, closes the temporary server, and exits. No Docker,
persistent local API, automated browser, or bundled Chromium is required.

```powershell
gpt-bridge auth status --json
```

## File fallback

Use this only when the one-shot local page is incompatible with your machine.

1. In your own signed-in browser, open a conversation and send a small message.
2. In Network tools, find the `POST` conversation request.
3. Copy the complete request as cURL, or copy its URL, headers (including
   Authorization and Cookie), and JSON payload together.
4. Save it to a private temporary file and import it locally. Do not paste it
   into an agent chat or screenshot.

```powershell
gpt-bridge auth import `
  --account main `
  --capture-file .\chatgpt-request.txt
```

GPT Bridge validates the local input and can live-check it after saving. A
capture can expire at any time; refresh it through the same user-controlled
flow when needed. Restarting Docker does not refresh a session.

## Local storage

```text
~/.config/gpt-bridge/accounts/<account>/chatgpt-request.txt
~/.config/gpt-bridge/accounts/<account>/settings.json
```

Docker explicitly uses `/data/secrets/accounts`. Stored captures are encrypted
by the existing account-store mechanism. On a shared machine, use a
passphrase-backed secret configuration where appropriate.

## Non-negotiable boundaries

- No password entry, stealth automation, normal-profile attachment, CAPTCHA
  solving, MFA bypass, or provider-control bypass.
- No public proxy, account sharing, resale, multi-tenant service, or LAN mode.
- Do not run copied cURL commands in a terminal or send raw captures to anyone.

## ภาษาไทย

วิธีหลักคือ `gpt-bridge setup` ซึ่งเปิดหน้า tokenized บน `127.0.0.1` ใน browser
ปกติ ใช้ ChatGPT tab ที่ login อยู่แล้ว copy request เป็น cURL มา paste ในกล่อง
ของหน้า local แล้วกด Save หากใช้ไม่ได้จึงค่อย import จากไฟล์ส่วนตัว Capture
เทียบเท่ารหัสผ่าน ห้ามแชร์หรือ commit และ restart Docker ไม่ได้ทำให้ session
กลับมาใช้ได้
