# Stronger blind isolation plan (2026-11-07)

Research: installed `codex exec --help` supports `--ephemeral`,
`--ignore-user-config`, `--ignore-rules`, explicit model and JSON event output.
Installed feature inventory supports disabling shell, apps, plugins and browser.
Official configuration reference: https://learn.chatgpt.com/docs/config-file/config-reference
Official security overview: https://learn.chatgpt.com/docs/security
Alternative installed Claude CLI has `--bare` and tool allowlists, but changes the
requested Luna model and authentication; reject for same-model cohort comparison.

1. Reuse existing isolated fixture body and installed MCP SDK. Add only missing
   stdio forwarding glue for genuine production registrations and private audits.
2. Prepare private temporary cwd/home and an explicit Codex command with no inherited
   provider configuration, no plugins/apps, shell, browser or skill discovery.
3. Before inference, capture a request against a local fake Responses endpoint;
   assert only the intended MCP tool names are exposed. Fail closed on other tools.
4. Do not start scored consumers. Give owner reproducible prepare/gate/run commands.
   Keep fixture trace and CLI usage separate. Report missing enforcement honestly.

Comparison: existing JSONL fixture is easy to audit but requires a relay; genuine
MCP preserves actual registrations and schema. Native CLI isolation is accepted
only after offline tool-surface evidence. A no-tools relay is the fallback, with
model output treated as data and only allowlisted JSON operations dispatched.
No new production dependencies, active downstream accounts or credential copies.

## Evidence and selected route

The native Codex offline gate failed: codex-cli 0.163.0 still exposed code-mode
`apply_patch`, MCP resources and collaboration tools despite the disable flags.
The fixture tool set was unavailable with the code-mode host disabled. Captured
requests and negative receipt: `/tmp/blind-cli-surface-second/`. No model inference
or account calls were made by that gate. Do not use it as a scored consumer.

Owner selected the existing Claude Pro login, Haiku, instead of installing an API
SDK or extracting credentials. `scripts/blind-claude-cohort.py` enforces the stream
initialization allowlist before accepting any tool execution: exactly eleven
`mcp__fixture__*` tools, one connected fixture MCP, no skills/slash commands, no
custom plugins, and no API-key source. The CLI reports built-in plugin and agent
metadata even with executable builtins disabled; these names are not extra tools.
`--safe-mode` was rejected because it also removes the explicit fixture server.
The surviving route uses restricted mode, empty builtin tools, strict MCP config,
disabled commands/hooks, no settings sources, sanitized environment, explicit
neutral system prompt, private empty cwd and no session persistence. No API key or
alternate provider environment variables are inherited; normal CLI Pro auth works.

Run from the repository root (new output directory required):

```sh
.venv/bin/python scripts/blind-claude-cohort.py --case probe --output /tmp/unique-probe
.venv/bin/python scripts/blind-claude-cohort.py --case A1 --output /tmp/unique-a1
.venv/bin/python scripts/blind-claude-cohort.py --case A2 --output /tmp/unique-a2
.venv/bin/python scripts/blind-claude-cohort.py --case B1 --output /tmp/unique-b1
.venv/bin/python scripts/blind-claude-cohort.py --case B2 --output /tmp/unique-b2
```

The startup probe passed at `/tmp/blind-claude-probe-3/`; two preceding unscored
probes aborted during initialization with zero tools called. A1/A2 use frozen
owner references MOSS-492/BERRY-329 and single-period briefs; B IDs are random,
preselected test-only values passed into the genuine queue seed. Each scored run
is a new CLI process and isolated owner, not a continuation. Keep logs private.

Artifacts per run: `command.json`, `prompt.txt`, `mcp.json`, `manifest.json`,
`events.jsonl`, `stderr.txt`, `fixture.jsonl`, `receipt.json`. The receipt includes
actual model ID, final text, CLI-reported usage, list-price cost metadata (not proof
of billing), call trace and wall time. The fixture separately records real MCP
arguments/results and final actual claim/effects. Local image paths and batch
operations are explicitly rejected and audited as unsafe attempts. No production
browser or provider is reached. This cross-provider cohort is not a Luna result.
