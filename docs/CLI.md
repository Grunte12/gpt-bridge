# GPT Bridge CLI

Use the installed command:

```sh
gpt-bridge <command>
```

`chatgpt-api` is a compatibility alias only. The internal Python module remains
`chatgpt_api`, but new scripts and documentation use `gpt-bridge`.

For the default direct worker, select one imported account:

```powershell
$env:CHATGPT_ACCOUNT = "main"
gpt-bridge worker doctor --json
```

Direct mode does not need Docker, a background service, a base URL, or an API
key. Chat and report default to `gpt-5-6-sol-high`.

## Agent-host integrations

Install native adapters for Codex, Claude Code, and OpenCode from a checkout:

```sh
python scripts/install-agent-integrations.py --dry-run
python scripts/install-agent-integrations.py
```

After the runtime is installed, register or refresh host integrations with:

```sh
gpt-bridge integrations install --target codex --target claude --target opencode
```

Repeat `--target` to select hosts. Use `--scope project` for project-scoped
Claude Code and OpenCode installation. The shared skill is installed for all
three hosts; OpenCode also receives native tools and keeps the current default
model unless `--set-opencode-default` is passed. Neither command starts the
Bridge or handles browser credentials.

## Everyday commands

```sh
gpt-bridge worker doctor --json
gpt-bridge worker chat --message "Summarize these notes" --json
gpt-bridge worker chat --message "Continue the analysis" --thread analysis --json
gpt-bridge worker thread list
gpt-bridge worker web list --query "brainstorm title" --json
gpt-bridge worker web show --conversation <id-or-url> --output context.md --json
gpt-bridge worker web pull --conversation <id-or-url> --output-path latest.png --json
gpt-bridge worker web send --conversation <id-or-url> --message "Turn the current thinking into the artifact I need." --json
gpt-bridge worker web delete --conversation <id-or-url> --yes --json
gpt-bridge worker report --prompt "Explain this data with useful charts" --out report.html --json
gpt-bridge worker image --prompt "Deliverable: clean product hero. Canvas: wide landscape. Content: one product. Constraints: no text, no unrelated objects, no watermark." --output-path work/image-draft.png --brief
gpt-bridge worker edit --prompt "Change only the background. Preserve the product and label." --input-image work/image-draft.png --output-path work/image-draft.png --brief
gpt-bridge worker image --prompt "Frontend asset: isolated organic ornament, no text or scenery." --output-path src/assets/generated/ornament.png --transparent --brief
gpt-bridge worker image --prompt "One-shot disposable concept, no text." --output-path work/one-shot.png --cleanup-session --brief
gpt-bridge worker research --prompt "Compare these options with sources" --json
```

The worker defaults to direct, one-account execution and exits after the
command. A `worker thread` is local JSON state. `worker web` instead works with
normal conversations already visible in the signed-in ChatGPT Web account:

- `web list` returns title/id/date metadata only so an agent can select safely;
- `web show` reads the current branch with message/character limits, or exports
  it to Markdown/JSON without filling the main agent context; and
- `web pull` downloads the latest assistant image (or every current-branch
  image on explicit request) into the local workspace; and
- `web send` fetches the latest current node and appends an arbitrary message,
  allowing ChatGPT to use the complete server-side session context; and
- `web delete` soft-deletes one exact selected conversation and requires
  `--yes`.

Use these as composable primitives rather than fixed workflow names. Prefer
`web send` when the desired output can be requested directly from the existing
session. Prefer `web show --output` when implementation needs original source
messages. A conversation URL is a private reference, not a credential.

`worker report` preserves complete
model-authored HTML without a fixed template. Treat output as untrusted active
content.

For images, agents should turn the user's request into one concise labeled spec
per attempt. Use `--brief` so the command returns output locations plus the
reusable ChatGPT Web conversation reference, reuse
one temporary draft path, and inspect only the latest draft. Regenerate or
refine as many times as needed for quality. Prefer an isolated worker or
subagent for this loop when the host supports one, returning only the accepted
path to the main task. Do not use legacy `--enhance` in normal agent flows. Put
intended use, canvas/composition, required content and relationships, visual
direction, exact quoted text, and constraints directly in `--prompt`. The
ChatGPT Web path does not expose reliable native `size` or `quality` controls,
so express those needs in the prompt.

Use `--cleanup-session` for a clearly one-shot image or edit with an explicit
local output. It soft-deletes the generated Web conversation only after the
file is saved and transparent-PNG conversion succeeds. Omit it for iterative
work, possible follow-up, or recovery. This is history cleanup, not a guarantee
of immediate server-side erasure.

The host sees only the installed skill description until the skill activates.
The activated body is a compact router that selects one deliverable
guide—frontend asset, photo, illustration, infographic, diagram, explanation,
product, UI, brand, story, scientific, spatial, or presentation—and only the
risk overlays relevant to that request. Detailed prompting instructions remain
on demand.

Use `worker edit` for a targeted correction or when source identity, product
geometry, brand elements, accepted composition, or multiple references must be
preserved. Number up to 10 source images in prompt order, state what each
contributes, and separate `Preserve`, `Change`, and `Forbidden changes`.

Use `--transparent` with an explicit `.png` output path for frontend assets.
The command verifies actual alpha. If native alpha is absent, it keys only a
flat edge-connected matte and fails safely when the background is too complex.
Inspect the PNG over light and dark backgrounds before frontend integration.

Presentation mode creates one complete 16:9 image per slide. After accepting
the ordered slide images, combine them with the script bundled inside the
installed skill:

```sh
python "$SKILL_DIR/scripts/images_to_pptx.py" \
  --out visual-deck.pptx \
  --title "Visual Deck" \
  slide-01.png slide-02.png slide-03.png
```

The resulting deck uses full-bleed flattened slide images, so its visible text
and graphics are not individually editable. Render and inspect every final
slide before delivery.

Use `gpt-bridge worker --transport http ...` only with an already-running local
API. HTTP mode accepts loopback URLs only.

## Account onboarding and lifecycle

```sh
gpt-bridge setup
gpt-bridge auth status --json
```

`setup` is the default no-daemon path. It opens a tokenized `127.0.0.1` form in
the normal browser. The user copies one conversation request from an existing
signed-in ChatGPT tab, pastes it into that local page, and clicks Save. GPT
Bridge validates and encrypts the capture under the stable per-user config
directory, verifies it, closes the temporary server, and exits. The equivalent
lifecycle command is:

```sh
gpt-bridge auth login --account main
```

When the one-shot setup page is incompatible, use
`gpt-bridge auth import --account main --capture-file <private-path>` or the
optional Console. Do not use multiline paste as the primary workflow.

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
gpt-bridge integrations install --help
gpt-bridge worker --help
gpt-bridge auth login --help
```

## ภาษาไทย

ใช้ `gpt-bridge setup` ครั้งแรกเพื่อเปิด browser แบบเห็นได้และให้ผู้ใช้ login เอง
จากนั้น agent เรียก `gpt-bridge worker` ได้โดยไม่ต้องเปิด Docker หรือ server
ถ้ามี capture เดียวไม่ต้องตั้ง `CHATGPT_ACCOUNT`; หาก setup ใช้ไม่ได้จึงค่อยใช้
Console หรือ import จากไฟล์ส่วนตัว ห้ามเปิด service ออก LAN/internet หรือแชร์
account/session ให้ผู้อื่น
