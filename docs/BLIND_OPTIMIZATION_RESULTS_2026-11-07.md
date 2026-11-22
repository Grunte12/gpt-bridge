# GPT Bridge: cold-agent acceptance results

**Final build: 8/8 fresh consumers passed.** Four original tasks and four English/Thai variants ran against the same product code, using `claude-haiku-5-5`. An independent evaluator checked each final answer *and* the isolated MCP audit. No production generation, restart, deploy, release, push, or clearing of drafts. This result is for two failure families, not every ChatGPT workflow and not a passing final Luna cohort.

| Case | Required behavior on the final build | Observed |
| --- | --- | --- |
| Book one image while a previous draft has an attachment | Preserve exact order ID and brief; create one queued job; explain the hold; do not remove the attachment or resubmit | 4/4, one `enqueue` per user, no dispatch |
| Read an original receipt after an interruption at the send boundary | Distinguish no confirmed local file from unknown remote outcome; inspect the original conversation only. No retry, reset, deletion or fabricated delivery | 4/4, four `job` reads plus one `status`; no new jobs |

Across the eight final attempts: **9 business calls, 0 tool errors, 0 unsafe mutations**. Median nine-call MCP round-trip 118 ms (12–277 ms); end-to-end cold CLI responses 15.49–20.19 s. These are measurements of this fixture, not ChatGPT image-generation latency. Provider-reported tokens: 32 uncached input, 26,234 cache creation, 56,432 cache reads, 5,217 output total; not an invoice. Earlier native Luna runs did not expose comparable token totals.

## What changed because a consumer failed

Previously a known draft hold could consume a full 120-second wait, three times across the first cohort. The original work now stays in the queue; `wait` returns immediately on a recognized actionable composer hold and a new heartbeat wakes an existing waiter. When ready, the same requests dispatch in FIFO order. Normal in-flight waits retain their timeout semantics. No reset-all or new production dependency.

The actionable receipt now leads with `agent_action: report_to_user_and_stop` and a customer-facing message. For interrupted `submit_attempted`, `remote_delivery: unknown` and `safe_to_retry: false` express facts, not an estimate based on a missing file. The message is also supplied in Thai for this ambiguous-write case. Other states retain their existing contracts; this is not a general prohibition on follow-up status reads. Exact caller order references are documented in the public schema. A scheduler fallback with no samples is not displayed as a customer generation estimate on these holds.

| First-attempt cohort | Result | Main failure retained |
| --- | ---: | --- |
| Luna 1 | 2/4 | Misreported a hold; long waits led to a sixth call |
| Luna 2 | 2/4 | Decorated an order ID; one consumer read a synthetic ID via the real gateway (unknown job, no write) |
| Isolated Haiku 3 | 0/4 | Safe tool calls, unsafe advice or unsupported claims in the final answer |
| Isolated Haiku 4 | 2/4 | Repeated polling; inferred that an empty chat justifies a new send |
| Isolated Haiku 5 | 4/4 original, 3/4 new wording | Thai answer treated an empty chat as proof |
| Isolated Haiku 6 | 3/4 original, 3/4 new wording | Attributed a transmission to a local intent record |
| **Isolated Haiku 7** | **4/4 original, 4/4 new wording** | Neither group needed coaching or replacement trials |

Method adapted from [Google's Elephant–Goldfish project](https://github.com/google/elephant-goldfish-model): the reviewer does not inherit the author's conversation. Hands-on consumers saw their individual task and actual MCP surface, not source, rubric or peer answers. The isolated host verified its executable tool inventory and allowed only the fixture MCP. The first less-isolated evaluations are deliberately reported separately. The small sample and repeated use of the frozen workloads do not establish a universal model success rate.

## Engineering gates on this checkout

- Python: **729 passed**, three opt-in legacy host integration tests skipped (separate from the real host trials above). Extension JavaScript: **477 passed**. A flaky VM helper now awaits a terminal event; it no longer assumes native hashing finishes in 50 event-loop ticks.
- Offline Chromium: **12 DOM scenarios** (8 composer/history/receiver, 4 native-upload). Missing thumbnail, pending and wrong-order uploads still refuse to send. Counts/flags explain upload failure without storing filenames or an unrelated conversation ID. None of the four historical upload incidents had enough evidence to diagnose its precise DOM cause.
- Two real stdio MCP clients and fixture owner: **26/26**. Joined MCP + actual MV3 worker/content script + real Chromium: **18/18**, including resumable FIFO, saved PNG hash, persisted restart state and clean browser exit. The ChatGPT document, pairing and generation result are fixtures; no live ChatGPT upload, image, or production compatibility claim. Hosted CI was wired, not run remotely.

Reproduce from the [frozen rubric](BLIND_ACCEPTANCE_2026-11-07.md), [CLI isolation protocol](BLIND_ISOLATION_PLAN.md), and [MV3 procedure](../tests/MCP_CHROMIUM_PLAN.md). [Sanitized per-case calls, timing, tokens and source fingerprints](evidence/BLIND_OPTIMIZATION_2026-11-07.json) are retained without live account or chat identifiers.
