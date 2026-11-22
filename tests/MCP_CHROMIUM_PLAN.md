# Joined offline readiness acceptance

Research: reuse `scripts/mcp-readiness-smoke.py` for the real stdio MCP and
ephemeral HTTP owner, and `tests/extension_content.chromium.test.cjs` for the
offline composer fixture. Playwright's official extension guidance uses a
fresh persistent Chromium context and unpacked MV3 extension:
https://playwright.dev/docs/chrome-extensions . Existing project tools already
cover the mechanics; no new dependencies or replacement browser framework.

Gap: neither existing test joins content inspection, worker heartbeat and real
MCP queue identity in one run.

1. Load a temporary extension copy with only the owner endpoint/host permission
   redirected to an ephemeral port. Keep actual content.js and worker logic.
   Check real MV3 worker and native tabs messaging are available.
2. Enqueue through two real stdio MCP sessions while an actual draft attachment
   blocks the browser. Check status/job/wait guidance and no delivery.
3. Remove the fixture draft, remove/reinstate the composer, then clean it.
   Check the same queued IDs regain readiness and dispatch once in FIFO order.
4. Synthetic image-job acceptance and PNG completion replace generation only.
   Check saved bytes/hash, queue reload persistence, and no later dispatch.

Seams: offline HTML is not ChatGPT; pairing credentials/config are fixture-owned;
image-job execution, lifecycle receipts and completion are synthetic. Readiness messages, browser
extension transport, worker heartbeat/claim, MCP, queue and disk persistence are
real. No user's Chrome, port 18767, provider call, or production dependency.

## Verified receipt (2026-11-07)

- [V] 18/18 joined checks passed on Playwright Chromium 156.0.8078.4, real MV3,
  including clean driver exit after browser/profile cleanup.
- [V] Two accepted MCP jobs remained queued for actual draft attachment and
  missing-composer DOM states, then dispatched in FIFO order exactly once.
- [V] Both 1882-byte PNG outputs were verified against saved bytes and SHA-256
  `7a91cfcb0d7152fcf303c7f2e7a917a9228c2fb52e48cb88270a50b8c660e89f`;
  queue reload retained complete status/hash. No page errors/unexpected requests.
- [V] Receipt: `/tmp/mcp-chromium-readiness.json` (temporary local receipt).
- [V] Branded Google Chrome did not load unpacked MV3 with these flags; supported
  Chromium works. Always use Playwright Chromium for this gate, a temporary
  profile, and no `nativeMessaging` permission in the temporary manifest.
- [?] CI is owned by the lead and not changed here. Live ChatGPT/real generation,
  native host pairing, extension restart and result extraction remain untested.

Run from repo root with installed Playwright and its Chromium:

```
PLAYWRIGHT_MODULE=/path/to/node_modules/playwright \
  .venv/bin/python scripts/mcp-chromium-readiness.py --output /tmp/joined.json
```

For the tested local temporary browser installation, also set
`PLAYWRIGHT_BROWSERS_PATH=/tmp/bridge-playwright-browsers`.

## VM waiter correction and stress evidence (2026-11-07)

- [V] Existing 50-`setImmediate` polling could expire before native SHA work
  completed. Reused Node's EventEmitter/once with a real 5-second abort bound;
  retain one event-loop turn after receipt for the producer's finally block.
- [V] Waiter regression checks 100 turns without false completion, timeout and
  multi-image receipts, no/malformed results, listener cleanup, and stale prior
  job receipts. Missing results now fail explicitly, not silently.
- [V] Six combined JavaScript repetitions passed 477/477 each while full pytest
  passed 728/3 skipped and three offline Chromium repetitions passed 2/2 each.
  Evidence: `/tmp/bridge-event-parallel-{node-*,browser-*,pytest}.log`.
- [V] CI's joined gate runs after Playwright and Chromium installation, uses the
  same module environment, and emits a machine-readable receipt to logs. No CI
  edits here. Temp manifest removes nativeMessaging; all non-loopback requests
  are fixture-fulfilled/blocked; context closes and temp files are finally removed.
- [V] Explicit clean-exit check exposed an open stdin keeping the driver alive;
  close the command stream before waiting for exit. No production code changed.
- [V] Final version (including stale-receipt cursor): four more combined JS runs
  passed 477/477 each; two concurrent joined runs passed 18/18 each. Logs/receipts:
  `/tmp/bridge-event-final-node-*.log`, `/tmp/bridge-event-final-joined-*.json`.
- [V] Concurrent focused Python load finished 260 passed/1 failed because another
  in-progress wording edit changed `inspect ChatGPT` to `Check the original
  ChatGPT conversation` in interrupted-job guidance. Not caused by the JS waiter;
  reported to lead rather than changing another worker's assertion.
