# Shared MCP concurrency evaluation

Date: 2026-11-01. Decision: retain one active worker tab by default.

## Final recommendation

Keep one MCP, one shared durable FIFO and one active Chrome worker. Multiple agents
submit independent jobs and wait on their own receipts. Do not enable a second real
tab on the basis of a scheduling model. The current bottleneck has not been shown
to be local queue dispatch; provider generation concurrency is still unmeasured.
This is a production-default decision, not proof that one tab has maximum throughput.

Actual local stress measurement: 30 rounds of six simultaneous callers, 180 unique
jobs, and 30/30 exclusive-claim races passed. Admission latency p50 0.736 ms / p95
1.405 ms; claim latency p50 0.192 ms / p95 0.382 ms. These timings include local queue
work only, not HTTP, image transfer, Chrome or ChatGPT. Values are one machine's
sample and not a performance guarantee.

Reproduce with `python -m scripts.eval_worker_pool --measure-queue` from the repo
using its installed dependency environment. It creates and removes temporary
synthetic queue directories; it does not touch the live queue or open Chrome.

## Verified production queue behavior

Regression tests use the actual ExtensionQueue with simultaneous Python threads:

- Six callers receive six distinct durable job IDs.
- Six simultaneous claims dispatch exactly one job, matching FIFO admission order.
- Sixteen simultaneous submissions admit exactly ten jobs and reject six without overflow.
- Existing tests cover result isolation, exact-chat cleanup blocking the next job, and restart recovery.

These are local queue tests, not six AI models or live ChatGPT generations.
FIFO order is lock admission order, not caller thread numbering.

Status now exposes capacity, waiting count, in-flight/cleanup count, and worker-tab count.
MCP instructions explicitly require each caller to track its own returned job_id; global
status can show somebody else's job. The queue does not deduplicate repeated submissions.

## Scheduling model (not measured generation performance)

Run `python scripts/eval_worker_pool.py`. The standard-library model compares one
and two lanes for six hypothetical jobs taking 40/90/30/120/60/50 seconds.

| Assumption | One lane | Two lanes | Interpretation |
| --- | ---: | ---: | --- |
| Independent processing | 390 s | 200 s | Potential gain only if the provider accepts parallel work |
| Account serializes processing | 390 s | 390 s | More tabs do not improve throughput |

The model also covers an account-wide 90-second start cooldown and uncertain
submission detection. A halt cannot undo work already dispatched in another lane;
the model records that work as in flight, rather than pretending it was cancelled.
Neither account serialization nor this cooldown is a claim about ChatGPT's actual limits.

## What remains before enabling two real tabs

Two lanes are not implemented in the Chrome Extension. A real pool requires exact
per-lane ownership, independent durable active-job state and output binding,
account-wide stop/cooldown handling, and safe tab restoration/cleanup. Do not simply
raise a concurrency constant or register a second MCP process.

Perform a quota-consuming controlled A/B run only after those contracts exist:
same workload under one and two lanes; record completion/queue wait p50 and p95,
total elapsed time, correct prompt-to-output binding, failures, duplicate sends,
throttling, and cleanup/restart correctness. Do not enable two lanes unless measured
throughput improves with zero cross-job results or duplicate submissions.

No live generation, quota use, production pool enablement, commit or release was
performed for this evaluation. Provider-aware rate limiting remains unimplemented;
single concurrency is not a requests-per-minute limit.
