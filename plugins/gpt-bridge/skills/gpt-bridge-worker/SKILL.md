---
name: "gpt-bridge-worker"
description: "Use the user's already-running local GPT Bridge API through `gpt-bridge worker` for routed chat, research, images, persistent task threads, or standalone HTML reports. Use only when the user asks to use their local GPT Bridge or continue a worker thread."
metadata:
  short-description: "Use a user-managed local GPT Bridge worker"
---

# GPT Bridge Worker

`gpt-bridge worker` is a local, loopback-only client for the user's already-running
GPT Bridge API. It is not a browser-capture tool, does not provide a
model directly, and never starts the Bridge service itself.

## Hard boundaries

- Never start, install, log into, capture, read, paste, or store browser session
  credentials on the user's behalf.
- Never expose the local service publicly or use it to bypass provider limits,
  conceal automation, or resell access.
- The worker accepts only loopback base URLs. A failed connection normally means
  the user-managed service is not running, not that an agent should repair or
  recreate it.
- Do not print `CHATGPT_API_KEY` or legacy `BRIDGE_TOKEN` values.

## Commands

```powershell
# Confirm the running service, health endpoint, and exposed models
gpt-bridge worker doctor --json

# One routed request or a local persistent task thread
gpt-bridge worker chat --message "..." --json
gpt-bridge worker chat --message "..." --thread planning --json
gpt-bridge worker thread list
gpt-bridge worker thread show planning

# Rich report: the model authors the entire offline HTML document, including
# advanced SVG/Canvas/JS charts when they make the answer clearer.
gpt-bridge worker report --prompt "..." --out report.html --json

# Image generation or Deep Research through the same routed service
gpt-bridge worker image --prompt "..." --enhance --json
gpt-bridge worker research --prompt "..." --json
```

`worker report` does not impose an HTML template or sanitize the model's report;
it saves the returned standalone document exactly so the model can choose the
most effective layout and visualization.

## Legacy transition

During the transition from `web-chat-bridge-cli`, `BRIDGE_URL` and
`BRIDGE_TOKEN` remain accepted as fallbacks for the worker connection. Import
old local thread files without modifying their originals:

```powershell
gpt-bridge worker migrate wcbridge --json
```
