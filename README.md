# GPT Bridge

**A local Web-session bridge and agent worker for your own machine.**

GPT Bridge is an independently maintained Python-first project. It combines a
local OpenAI-compatible Bridge API with the worker workflow previously kept in
`web-chat-bridge-cli`:

- routed chat, images, vision, and Deep Research through one local API;
- a loopback-only `worker` CLI for agents and automation;
- persistent local task threads and non-destructive legacy migration;
- model-authored standalone HTML reports, including charts or interaction when
  that is the clearest answer; and
- a local operator console for account and runtime management.

> ภาษาไทย: GPT Bridge คือโปรเจกต์ Python-first ที่พัฒนาต่ออย่างอิสระ รวม Bridge API
> เดิมกับ workflow จาก `web-chat-bridge-cli` ไว้ในตัวเดียว สำหรับรันบนเครื่องของ
> คุณเอง ไม่ใช่ hosted service หรือ official OpenAI API

## Project direction

The original bridge and the separate web CLI are no longer treated as two
products. GPT Bridge is the source of truth:

| Component | Responsibility |
| --- | --- |
| Bridge API | Account routing, model fallback, OpenAI-shaped API, images, vision, research, artifacts |
| Worker CLI | Agent-friendly chat, task threads, reports, migration, doctor, conservative stack controls |
| Console | Local browser UI for accounts, health, capacity, storage, and API tools |
| Codex plugin | A local skill that teaches Codex to call the worker without touching browser credentials |

The project intentionally does **not** retain a Node/Bun runtime for the old
worker client. The old executable names remain as compatibility aliases while
their supported commands forward to the Python worker.

> ภาษาไทย: เป้าหมายคือให้ `gpt-bridge` เป็นตัวหลักเพียงตัวเดียว: API ดูแล
> routing/provider, worker ดูแลงาน agent และ state, ส่วน Console ใช้จัดการ
> ทั้งหมดแบบ local

## Important boundaries

- This is not an official OpenAI product or API.
- A ChatGPT Web capture contains credentials. Treat it like a password.
- Never commit, share, paste into chat, or expose captures/cookies/tokens.
- Do not turn this into a public proxy, multi-tenant service, resale endpoint,
  or a mechanism to evade provider limits.
- Browser login and capture are manual user actions. The worker and Codex plugin
  must never perform them for you.

Read [DISCLAIMER.md](DISCLAIMER.md) and [SECURITY.md](SECURITY.md) before
using a Web session. This is an unofficial local experiment, not a hosted or
shared proxy, and it must not be used to bypass provider controls.

> ภาษาไทย: อย่าแชร์ cookie, bearer token หรือ request capture ให้ใคร รวมถึงใน
> chat นี้ด้วย ให้ใส่เฉพาะใน Console ที่รันอยู่บนเครื่องของคุณเอง

## Quick start: Docker

Prerequisites: Docker Desktop/Compose and a local checkout of this repository.

On Windows, the simplest setup creates a random local key and starts the two
default services:

```powershell
.\scripts\setup-local.ps1
```

It creates or preserves `.env`, never prints the key, and tells you where to
enter it in the Console. To prepare configuration without starting Docker, use
`.\scripts\setup-local.ps1 -NoStart`.

Build and start the current source version:

```powershell
docker compose build gpt-bridge bridge-console
docker compose up -d gpt-bridge bridge-console
docker compose ps
```

Open these local surfaces:

| Surface | Address | Purpose |
| --- | --- | --- |
| Bridge Console | <http://127.0.0.1:8080> | Browser UI for accounts and operations |
| Health | <http://127.0.0.1:8000/health> | API readiness check |
| API base | <http://127.0.0.1:8000/v1> | OpenAI-compatible API base URL |

The API intentionally has no homepage: `http://127.0.0.1:8000/` returns a
JSON `not_found` response. Use `/health`, `/v1/...`, or the console on `:8080`.

> ภาษาไทย: ถ้าเปิดพอร์ต `8000` แล้วเห็น `not_found` ถือว่าปกติ API ไม่มีหน้า
> root ให้เปิด Console ที่ `http://127.0.0.1:8080` แทน

### Add or refresh an account capture

#### Experimental easy path: visible local browser

Run this while the local bridge is running. GPT Bridge installs the required
browser library with the package; the first login may download bundled Chromium.

```powershell
gpt-bridge auth login --account main --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
```

Read the consent text, choose **yes**, then sign in and send one small message
in the visible isolated Chrome window. The command never prints the session,
stores it only through the existing encrypted local account store, and removes
the temporary browser profile. Before an interactive save it asks for one final
confirmation. Use `gpt-bridge auth status` to inspect only non-secret local
state or `gpt-bridge auth logout --account main` to delete it. If Chrome is not
installed, the first login run downloads a local bundled Chromium automatically.
This flow is experimental: service changes or browser checks can make it fail.

> ภาษาไทย: วิธีนี้เปิด Chrome profile ชั่วคราวให้ผู้ใช้ login เอง แล้วส่งข้อความ
> สั้น ๆ หนึ่งครั้ง ระบบจะไม่แสดงหรืออัปโหลด session และจะลบ profile ชั่วคราวหลังจบ
> หากใช้ไม่ได้ ให้ใช้วิธี paste capture ด้านล่าง ซึ่งยังคงเป็น fallback แบบ local
> เท่านั้น

#### Manual fallback: copied request capture

1. Open the Console and go to **Accounts**.
2. Choose **Add account** or update an existing local account alias.
3. In your own signed-in browser, collect a fresh ChatGPT request using the
   Console guidance (full `Copy as cURL` or the required headers and payload).
4. Paste it only into the local Console and save. The Console validates and
   live-verifies it before the router uses it.

CLI alternative:

```powershell
gpt-bridge admin account add --paste `
  --base-url http://127.0.0.1:8000/v1 `
  --api-key YOUR_LOCAL_KEY
```

If a request returns `token_invalidated`, refresh the capture through this flow.
Restarting Docker does not refresh ChatGPT credentials.

> ภาษาไทย: หากเจอ `token_invalidated` ให้ capture ใหม่ผ่าน Accounts ใน Console
> การ restart Docker ไม่สามารถแก้ token ที่หมดอายุได้

## Worker: the unified agent interface

Install locally for development:

```powershell
python -m pip install -e ".[dev]"
```

Check the local service:

```powershell
gpt-bridge worker doctor --json
gpt-bridge worker status --json
```

Use chat with an optional durable local task thread:

```powershell
gpt-bridge worker chat --message "Review this implementation" --json
gpt-bridge worker chat --message "Continue from the previous findings" --thread review --json
gpt-bridge worker thread list
gpt-bridge worker thread show review
```

The worker accepts only loopback base URLs (`127.0.0.1`, `localhost`, or `::1`).
It cannot become a generic outbound proxy.

> ภาษาไทย: `worker` เป็น CLI สำหรับ Codex/agent และงาน automation โดยเรียกได้
> เฉพาะ Bridge ที่รัน local เท่านั้น Thread เก็บ context ของ task ไว้ในเครื่อง

### Rich HTML reports

`worker report` does not force Markdown or a fixed HTML template. The model
returns the complete report document, which is saved as-is. It may choose inline
CSS, SVG, Canvas, or JavaScript for charts and interaction when appropriate.

```powershell
gpt-bridge worker report `
  --prompt "Analyse monthly revenue and choose useful charts" `
  --out .\outputs\revenue-report.html `
  --json
```

The CLI does not automatically open the file.

The returned HTML is not sanitized. Treat it as untrusted active content and
inspect it before opening it in a browser.

> ภาษาไทย: report ให้โมเดลเลือกวิธีนำเสนอที่มีประสิทธิภาพที่สุดเอง ไม่ถูกล็อก
> ด้วย template จึงทำกราฟหรือ interaction ขั้นสูงได้

### Images and Deep Research

```powershell
gpt-bridge worker image --prompt "A clean product hero image" --enhance --json
gpt-bridge worker research --prompt "Compare these options with sources" --json
```

Image enhancement is best-effort: if its preparatory chat call fails, image
generation continues with the original prompt and reports the warning. Deep
Research can be long-running and consumes the account's available capacity.

## Legacy web-chat-bridge-cli transition

The Python worker replaces the old Node CLI. These commands remain available
during the compatibility period:

```powershell
web-chat-bridge status --json
wcbridge doctor --json
```

They print a deprecation notice and forward supported commands to
`gpt-bridge worker`. The former `chatgpt-api` command remains a compatibility
alias. Legacy environment variables are accepted as fallbacks:

| New setting | Compatibility fallback |
| --- | --- |
| `CHATGPT_BASE_URL` | `BRIDGE_URL` |
| `CHATGPT_API_KEY` | `BRIDGE_TOKEN` |
| `CHATGPT_WORKER_DATA_DIR` | `WCBRIDGE_DATA_DIR` |
| `CHATGPT_STACK_DIR` | `WCBRIDGE_STACK_DIR` |

Import old worker threads without changing or deleting their originals:

```powershell
gpt-bridge worker migrate wcbridge --json
```

> ภาษาไทย: คำสั่งเก่าใช้ต่อได้ชั่วคราว แต่ควรย้ายมา `gpt-bridge worker` และใช้
> `migrate wcbridge` เพื่อ copy thread เดิมอย่างปลอดภัย

## API usage

The server exposes an OpenAI-shaped local API. Use a local bearer key in real
deployments instead of leaving the development default in place.

```powershell
curl http://127.0.0.1:8000/v1/models `
  -H "Authorization: Bearer YOUR_LOCAL_KEY"
```

```powershell
curl http://127.0.0.1:8000/v1/chat/completions `
  -H "Authorization: Bearer YOUR_LOCAL_KEY" `
  -H "Content-Type: application/json" `
  -d '{"model":"auto","messages":[{"role":"user","content":"Reply in one short sentence."}]}'
```

Useful endpoints:

| Route | Use |
| --- | --- |
| `GET /health` | Liveness/readiness |
| `GET /v1/models` | Exposed model aliases |
| `POST /v1/chat/completions` | Chat and streaming |
| `POST /v1/images/generations` | Image generation |
| `POST /v1/images/edits` | Image edit/composite |
| `POST /v1/chatgpt/vision` | OCR and image description |
| `POST /v1/chat/completions` with Deep Research | Long-running research |
| `GET /v1/chatgpt/admin/status` | Local runtime status |

See [docs/OPENAI_COMPATIBILITY.md](docs/OPENAI_COMPATIBILITY.md) for request
shapes and [docs/CLI.md](docs/CLI.md) for the complete CLI reference.

## Models, routing, and accounts

Account names are your own local aliases, not subscription-plan names. The
router can select one account or route across a temporary account pool using
strategies such as `failover`, `random`, `round-robin`, or `quota-aware`.

```powershell
gpt-bridge api chat `
  --message "Summarize these notes" `
  --accounts work-main,personal-main `
  --account-strategy failover `
  --base-url http://127.0.0.1:8000/v1 `
  --api-key YOUR_LOCAL_KEY
```

Model aliases reflect what the local account/router exposes. Inspect them
instead of hard-coding assumptions:

```powershell
gpt-bridge worker doctor --json
gpt-bridge admin models --json --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
```

> ภาษาไทย: ชื่อ account เช่น `personal-main` เป็น alias ในเครื่อง ไม่ใช่ plan
> ของ ChatGPT และ model ที่ใช้ได้จริงควรดูจาก `worker doctor` หรือ `admin models`

## Conservative stack controls

For an existing Compose checkout, the worker can control only known lifecycle
operations. It never builds images automatically and never removes volumes.

```powershell
$env:CHATGPT_STACK_DIR = "C:\path\to\gpt-bridge"
gpt-bridge worker stack status --json
gpt-bridge worker stack restart
```

## Codex plugin

The plugin source lives at [plugins/gpt-bridge](plugins/gpt-bridge). Its skill
documents when Codex may use the local worker and the strict credential
boundaries it must keep. If you maintain it with the Codex CLI's
plugin-creator skill, validate it with that skill's `validate_plugin.py`
script against `./plugins/gpt-bridge`; otherwise review
`plugins/gpt-bridge/.codex-plugin/plugin.json` manually.

> ภาษาไทย: plugin นี้ไม่ได้ให้ Codex login หรือจับ cookie แทนคุณ มันเพียงเรียก
> `gpt-bridge worker` ไปยัง Bridge local ที่คุณเปิดและตั้งค่าเองแล้ว

## Verification

Current local release-candidate checks include:

```powershell
python -m compileall -q chatgpt_api
python -m pytest -q
git diff --check
docker compose build gpt-bridge bridge-console
docker compose up -d gpt-bridge bridge-console
gpt-bridge worker doctor --json
```

The full provider-facing checks (`worker chat`, reports, images, and research)
require a live account capture. A `token_invalidated` response is an account
credential refresh issue, not a Docker readiness issue.

## Repository map

```text
chatgpt_api/                 Python Bridge API, providers, worker, compatibility CLI
chatgpt_api/worker/          Loopback client, storage, migration, stack controls
apps/bridge-console/         Svelte operator console
plugins/gpt-bridge/          Codex plugin and worker skill
integrations/                Consumer integrations and examples
docs/                        Architecture, API compatibility, CLI, handoff notes
tests/                       Python regression suite
```

## Documentation

- [CLI reference](docs/CLI.md)
- [OpenAI compatibility](docs/OPENAI_COMPATIBILITY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Provenance and release boundary](PROVENANCE.md)

## License and responsibility

This repository is MIT-licensed. You are responsible for complying with the
terms and policies that apply to your ChatGPT account and any services you
connect. Keep the Bridge local, protect its credentials, and verify outputs
before using them for important decisions.

The license covers this repository's code only; it grants no rights to OpenAI,
ChatGPT, their marks, or any third-party service. See [DISCLAIMER.md](DISCLAIMER.md).

> ภาษาไทย: ใช้โค้ดภายใต้ MIT ได้ตามเงื่อนไข แต่คุณต้องรับผิดชอบการใช้งาน account
> และผลลัพธ์ของระบบเอง ควรรัน local, ปกป้อง credentials และตรวจคำตอบก่อนใช้จริง
