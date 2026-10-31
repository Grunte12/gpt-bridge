# Extension image workflow

See the maintained [installation and commands](../README.md).

GPT Bridge uses the ChatGPT login in the paired Chrome tab. There is no main or
second account requirement and no cookie capture. Do not launch a dedicated
browser profile or run legacy session setup.

Run `gpt-bridge mcp` from your MCP client. For multiple hosts, run one shared
`gpt-bridge mcp --serve` owner and connect clients with `gpt-bridge mcp --connect`.
The installing agent registers Native Messaging using
`gpt-bridge install-native --extension-id <actual GPT Bridge Chrome ID>`.
On startup the Extension connects itself and opens one background work tab in
the existing Chrome profile. No Connect click or manual pairing-code entry is
needed. Existing user tabs and active/uncertain work are not adopted or replaced.

Check `status`, submit `generate` or `edit` once, then follow the same job using
`wait` or `job`. `preflight` tests uploads without sending. Saved receipts
include image paths and cleanup outcome. Never interpret a timeout as permission
to generate again. Inspect uncertain work and use the live `resolve` schema.

Local pairing, exact tab markers, origin validation, upload budgets, durable job
receipts and per-job cleanup approvals remain in place. Changing account naming
does not relax those protections. Existing data in the historical `second`
directory is retained; that directory is not proof of a browser account.

Use `status` diagnostics and the Extension popup for reconnect/reload. Reload
only when idle. Keep Chrome open and do not switch logins during an active job.
The current Extension implements image generation/editing only, not legacy CLI
chat, research, web-session export, or report generation.
