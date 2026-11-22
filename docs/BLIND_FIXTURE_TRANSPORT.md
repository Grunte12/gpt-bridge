# Isolated consumer transport

Start from the repository root, once per independent trial:

```sh
.venv/bin/python scripts/blind-consumer-fixture.py --scenario A --log /tmp/unique-a-audit.jsonl
.venv/bin/python scripts/blind-consumer-fixture.py --scenario B --log /tmp/unique-b-audit.jsonl
```

The audit path must not already exist. Local loopback listening permission is required.
Each process creates a fresh temporary queue and HTTP owner; the installed MCP SDK
opens the actual production MCP tool server in a separate stdio child. No production
state, browser, provider, credentials or generation are used. Stop with `quit` or EOF;
the temporary queue is removed, but the requested audit remains.

The first stdout JSON line contains `ready`, the actual MCP initialization
`instructions`, and `known_job_id` (only B). Pass B's known ID in its task text.
MCP diagnostic messages are on stderr, not the JSON protocol. Consumer commands:

```json
{"op":"list"}
{"op":"describe","name":"enqueue"}
{"op":"call","name":"status","arguments":{}}
{"op":"quit"}
```

`list` projects real names/descriptions; `describe` returns the named real schema;
`call` returns the unmodified SDK result. This is a client interface, not a substitute
tool implementation. Keep private audit files and this setup description away from
blinded consumers. The owner's separate opaque exchange wrapper may relay JSONL.

Private setup A: paired synthetic tab 71 reports a foreign attachment blocker.
Private setup B: real enqueue (`prior-order-uncertain`, cobalt blue teapot brief),
claim, and `submit_attempted` phase receipt; restarting the queue makes the original
interrupted and halts the line. IDs are random and returned at startup. Nothing is
actually sent to ChatGPT. Every business call refreshes the synthetic heartbeat.

Audit records separate discovery, business arguments/results, before/after durable
job snapshots, elapsed monotonic time, per-call duration, seed delivery, final actual
claim attempt and final effects. Do not infer token usage from these measurements.

Checks performed: A real stdio enqueue returned queued, `existing_attachments` and
`preserve_paired_attachments`; B real stdio status after explicit phase/restart
returned `inspect_halted_job` and the original ID. These are fixture checks, not
consumer acceptance outcomes or real Chrome evidence.
