# Agent-facing readiness: acceptance plan

Research: the preceding review compared MCP Conformance, Chrome Extension service-worker termination tests, BullMQ's idempotent-jobs guidance and Hypothesis state machines. Reuse this repo's existing claim, heartbeat, queue receipts and browser fixture, not another broker or retry engine.

Earlier baseline extract (durable generation jobs excluding preflight and collect-only): 337 jobs. Of the 30 failures recorded in prepared, 13 reported composer unavailable, 13 existing attachments, and four upload verification failures. This extract is **not** a strict 1–6 Nov Bangkok cohort: the fourth upload record was 7 Nov 00:15 local time. See [the timestamp audit](NATIVE_UPLOAD_ACCEPTANCE_2026-11-07.md). An error string is not proof the draft was empty or that sending is safe.

1. Ignore only demonstrably historical attachment previews. Preserve actual drafts, ambiguous attachment evidence, completed-chat preparation and explicit recovery operations.
2. Keep ordinary jobs queued, not irreversibly claimed, while a heartbeat proves a matching blocker. Surface a bounded reason and next action to the MCP consumer, plus queue/phase durations when observed. Clear the hold using a healthy heartbeat, not a destructive reset.
3. Check duplicate caller IDs, two-agent FIFO, persistent waiting jobs and recovery exceptions with isolated fixtures. Independently exercise a real MCP client and synthetic browser worker. No live generation, reload, mass resolve or state removal.

Agent contract: call enqueue once with a stable request ID. A queued receipt is not a failed generation. If present, wait_reason describes the current obstacle; queue_wait_ms is elapsed time, not an ETA. For preserve_paired_attachments, do not clear an unfamiliar draft. For inspect_paired_composer, inspect the bound tab, not another profile. Once the blocker is absent, the next healthy poll claims the original job. Do not submit a replacement. stage_ms reports observed queue, generation and save intervals only; absent means not measured.

Run the offline gates from the repo root:

- `python -m pytest -q tests/test_readiness_hold.py tests/test_extension_pending.py`
- `python scripts/mcp-readiness-smoke.py --output /tmp/bridge-smoke.json` (two stdio MCP sessions; real isolated loopback service, synthetic Chrome)
- `node --test tests/extension_content.test.cjs tests/extension_worker.test.cjs`
- `node --test tests/extension_content.chromium.test.cjs` (requires Playwright and Chromium in the **test** environment; offline page fixture, real DOM, mocked Chrome runtime messaging). CI provisions these separately from end-user installs.

These gates do not prove live ChatGPT availability or actual MV3 eviction. Measure before/after on comparable live workloads, separating queue wait from generation time; do not extrapolate from fixture timings. Native-upload verification failures remain out of scope. No global reset, extra worker, new end-user dependency or new MCP tool.
