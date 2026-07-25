# GPT Bridge CLI

Use the installed command:

```sh
gpt-bridge <command>
```

`chatgpt-api` is a compatibility alias only. The internal Python module remains
`chatgpt_api`, but new scripts and documentation use `gpt-bridge`.

Set the local connection once per host shell:

```powershell
$env:CHATGPT_API_KEY = "YOUR_LOCAL_KEY"
$env:CHATGPT_BASE_URL = "http://127.0.0.1:8000/v1"
```

The key is generated in `.env` by `./scripts/setup-local.ps1`. It is required;
`local-dev-key` is rejected.

## Everyday commands

```sh
gpt-bridge worker doctor --json
gpt-bridge worker chat --message "Summarize these notes" --json
gpt-bridge worker chat --message "Continue the analysis" --thread analysis --json
gpt-bridge worker thread list
gpt-bridge worker report --prompt "Explain this data with useful charts" --out report.html --json
gpt-bridge worker image --prompt "A clean product hero image" --enhance --json
gpt-bridge worker research --prompt "Compare these options with sources" --json
```

The worker accepts loopback URLs only. A thread is local JSON state; it does
not resume a browser conversation. `worker report` preserves complete
model-authored HTML without a fixed template. Treat output as untrusted active
content.

## Account onboarding and lifecycle

```sh
gpt-bridge auth login --account main --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
gpt-bridge auth status --json
gpt-bridge auth logout --account main --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
```

The user performs sign-in, MFA, and any challenge in the visible browser. When
that flow is incompatible, use the manual workflow in `docs/ACCOUNT_CAPTURE.md`
or the Console's **Accounts** page.

## Local server and administration

```sh
gpt-bridge serve --host 127.0.0.1 --port 8000 --api-key YOUR_LOCAL_KEY
gpt-bridge admin status --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
gpt-bridge admin models --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
gpt-bridge admin account verify --account all --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
gpt-bridge api chat --message "Reply in one sentence" --model auto --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
gpt-bridge api image --prompt "small blue icon" --base-url http://127.0.0.1:8000/v1 --api-key YOUR_LOCAL_KEY
```

Use account aliases you created locally, such as `main` or `image-pro`; they
are not subscription plans. Routing strategies such as `failover` are local
tools, not a way to bypass account limits.

## Compatibility and conservative stack control

`web-chat-bridge` and `wcbridge` forward supported commands to
`gpt-bridge worker` and print a deprecation message. `worker migrate wcbridge`
copies legacy thread files without deleting their originals.

If `CHATGPT_STACK_DIR` points at a Compose checkout, `worker stack` invokes
only conservative lifecycle commands. It never removes volumes or builds an
image automatically.

## Help

```sh
gpt-bridge --help
gpt-bridge worker --help
gpt-bridge auth login --help
```

## ภาษาไทย

ใช้ `gpt-bridge` เป็นคำสั่งหลัก ตั้ง `CHATGPT_API_KEY` จาก `.env` ก่อนเรียก
worker หรือ admin จาก host เครื่องเดียวกัน `auth login` เปิด browser แบบเห็นได้และ
ให้ผู้ใช้ login เอง หากใช้ไม่ได้ให้ใช้ Console หรือ capture แบบ manual ห้ามเปิด
service ออก LAN/internet หรือแชร์ account/session ให้ผู้อื่น
