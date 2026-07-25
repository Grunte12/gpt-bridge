# GPT Bridge + OpenCode integration

OpenCode is an optional consumer of GPT Bridge's local OpenAI-shaped API. It is
not the control plane and it never receives browser credentials directly.

## Current contract

- Start GPT Bridge locally, then configure OpenCode to use
  `http://127.0.0.1:8000/v1` and the local `CHATGPT_API_KEY`.
- The recommended model is `chatgpt-web/auto@optimized`; use a model listed by
  `gpt-bridge worker doctor --json` rather than guessing availability.
- OpenCode executes tools. GPT Bridge returns compatible chat/tool-call
  responses and does not take over OpenCode's filesystem or shell permissions.
- GPT Bridge image, edit, vision, and research operations are separate API/CLI
  workflows. OpenCode attachments are not automatically converted into upload
  requests.
- Local OpenCode settings may live under `~/.config/gpt-bridge/`; raw captures
  never belong there.

## Setup

See `integrations/opencode/README.md`. The setup helper only writes consumer
configuration. It must not start browser capture, expose the bridge, or weaken
OpenCode permission controls.

## Boundaries

Keep `--dangerously-skip-permissions` out of normal work. Do not run concurrent
OpenCode commands against one OpenCode state database. Do not use this
integration to share accounts, create a hosted service, or bypass provider
controls.

## Maintenance rule

When a model alias changes, update provider capability checks, `/v1/models`,
the example integration config, and user docs together. Validate with a
user-operated local account; a name seen in a UI is not sufficient proof of a
working wire-level model identifier.
