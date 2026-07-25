# OpenCode with GPT Bridge

OpenCode is an optional client of GPT Bridge's local OpenAI-shaped API. It does
not log in, capture a browser session, or manage account credentials.

## Before configuring OpenCode

1. Start the local stack with `./scripts/setup-local.ps1` (Windows) or your own
   local `gpt-bridge serve` command.
2. Copy the unique `CHATGPT_API_KEY` from ignored `.env` into the shell or setup
   prompt. Do not use `local-dev-key`; the server rejects it.
3. Confirm the service locally:

```powershell
$env:CHATGPT_API_KEY = "YOUR_LOCAL_KEY"
$env:CHATGPT_BASE_URL = "http://127.0.0.1:8000/v1"
gpt-bridge worker doctor --json
```

## Configure the OpenCode consumer

Run the interactive helper:

```sh
bun integrations/opencode/chatgpt-opencode.mjs
```

It asks for the local base URL, bearer key, and model, then writes only the
OpenCode consumer configuration. It does not start Docker, change routing,
capture a session, or expose any service.

For scripts:

```sh
bun integrations/opencode/opencode-config.mjs --inject \
  --base-url http://127.0.0.1:8000/v1 \
  --api-key YOUR_LOCAL_KEY \
  --model chatgpt-web/auto@optimized
```

Use `--status` to inspect the generated configuration and `--eject` to remove
it. The example provider configuration is in `opencode.example.json`.

## Normal use

After configuration, run OpenCode normally:

```sh
opencode .
```

`chatgpt-web/auto@optimized` is the recommended default. Verify currently
available models with `gpt-bridge worker doctor --json`; a model name shown in
another UI is not a guarantee that this local account can use it.

OpenCode executes tools and keeps its own permissions. Do not use
`--dangerously-skip-permissions` for ordinary work.

## Boundaries

- Keep the API on `127.0.0.1`; GPT Bridge has no supported LAN/public mode.
- Do not place account captures, cookies, or copied browser requests in
  OpenCode configuration.
- Image/vision/research work is available through GPT Bridge's explicit API or
  worker commands; OpenCode attachments are not automatically turned into
  provider uploads.
- Do not use the integration for account sharing, hosted access, resale, or
  provider-limit bypass.

## ภาษาไทย

OpenCode เป็นเพียง client ของ GPT Bridge local เท่านั้น ก่อนตั้งค่าให้เปิด stack
บนเครื่องและใช้ key จริงจาก `.env` จากนั้นรัน helper ข้างบนเพื่อเขียน config ของ
OpenCode ห้ามใส่ cookie/capture ลง config และห้ามเปิด API ออก LAN/internet
