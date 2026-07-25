# Screenshot Evidence

These screenshots are captured from the Docker stack, not static mockups.

## Captured Views

| File | Source | What it proves |
| --- | --- | --- |
| `oss-console-overview.png` | `http://127.0.0.1:8080` | Bridge Console loads from the nginx Docker image, reads API health from `:8000`, shows route capacity, model count, download routes, and operational status. |
| `oss-console-accounts.png` | `http://127.0.0.1:8080/#accounts` | Account capture management is exposed as a first-class console page with ASCII account-name validation, capture inspection, update, verify, and delete controls. |
| `oss-console-docs.png` | `http://127.0.0.1:8080/#api-docs` | Console embeds API route docs with request/response shape guidance, including chat, images, edits, vision/OCR, research, files, admin routes, and cancel routes. |
| `oss-console-library.png` | `http://127.0.0.1:8080/#storage` | The storage/library plane is separated from runtime controls and is ready to show completed images and research reports with download URLs. |
| `oss-console-opencode.png` | `http://127.0.0.1:8080/#opencode` | opencode is configured as a consumer integration, not as the whole product control plane. |

## Re-Capture

Run the stack:

```sh
docker compose up -d --build
```

Install the Console's locked dependencies and Chromium once, then run the
repeatable local capture command:

```sh
cd apps/bridge-console
bun install --frozen-lockfile
bunx playwright install chromium
bun run screenshots:capture
```

It captures the documented Console URLs into this directory, masks
sensitive form values, and fails if visible page text contains recognizable
session/token material. It does not start Docker, acquire a capture, or make
network requests outside the already-running local URLs. `BRIDGE_CONSOLE_URL`
can override the local Console base URL for a nondefault local stack.

Review every generated image before committing it. Do not commit screenshots
that expose session cookies, copied captures, bearer tokens, or personal account
names you do not want shown.
