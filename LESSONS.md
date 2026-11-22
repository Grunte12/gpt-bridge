# Lessons

- 2026-11-18: Four jobs "timed out" at 600 s with a finished image in the chat, then a failed chat delete blocked every heartbeat. Rule: never believe a timeout from a tab nobody looked at; reload the exact chat visibly and recheck first. A cleanup failure is a note on the job (`preserved`), never a queue lock. Also: the poll-driven visible-output collect had never sent its phase receipts, and a `const state` reassignment broke the post-restart delete; an untested recovery path is a broken one.

- 2026-11-18: Images were finished in ChatGPT but jobs timed out at 600 s, because the unpacked extension had moved to 0.1.45 while the service stayed on an older release. Rule: an extension reload and a service release ship as one matched pair; status must show running_extension_version listed in the live OUTPUT_BINDING_REVISIONS. A 400 heartbeat is silent: log non-200 replies when pairing stalls.
- 2026-11-07: A cold consumer used a real gateway for a fake receipt despite instructions. Verify the isolated host's executable tool inventory before trials; grade both its actual calls and the advice it gives the user after the receipt.
- 2026-11-07: `submit_attempted` is recorded **before** clicking Send, not proof of submission; an empty chat after restart is not evidence that a second send is safe.
- 2026-11-07: CPU load exposed a VM test that stopped after 50 event-loop ticks rather than waiting for the matching completion. Gate on the actual terminal event with a deadline, not scheduler speed.

- 2026-11-07: A reachable content listener can report a blocked composer; prove readiness before durable claim, distinguish submitted-history thumbnails from current drafts, and test two real MCP consumers against a blocked-to-ready heartbeat.

- 2026-11-05: Durable waiting jobs initially blocked normal re-pairing after restart; test actual heartbeat recovery, exclude only accepted never-delivered requests bound to that same extension, and never treat a stopped batch as permission to dispatch.
