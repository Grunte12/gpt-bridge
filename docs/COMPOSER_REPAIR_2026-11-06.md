# Focused composer repair

## Research and evidence

- [V] Live MCP job `6484f656cada4d9eb6f89f28403f2730` failed in `prepared` with composer unavailable. No generated output or submit-phase receipt. It must not be automatically replayed.
- [V] Initial live status: installed/running 0.1.45, queue depth 0, inflight/cleanup 0. This is a snapshot, not permission to reload later without a fresh check.
- [V] Existing content code recognizes exact legacy ID and exact English role/contenteditable/label combination. `idleEditor` duplicates that selector. Reuse this implementation; no new automation library or browser owner is needed.
- [V] GitHub discovery checked existing ChatGPT selector work, including https://github.com/mvanhorn/agent-tincan/blob/main/docs/adapters/web-agents.md and https://github.com/TimMacy/ReadAloudSpeedster/issues/4 . Search results show bounded native editor selectors, but fetching those pages failed; they are discovery leads, not proof of this tab's markup.
- [V] Chrome DevTools reports no browser context. Browser inventory and native accessibility refer to different Chrome profiles. Source reports the affected tab in profile Nba. Actual composer DOM attributes are not yet verified.
- [V] Nba maps to Chrome `Profile 2`; its installed GPT Bridge ID is `ncdlnoaflpohjgipmfapkbekapikliom`, loading the canonical repo extension. Native Messaging `allowed_origins` names that exact extension ID. This verifies install authorization, not the currently paired browser tab. Failed job metadata binds browser tab `1652896704`; elapsed claim-to-failure is about 15.64 seconds, consistent with the existing 15-second preparation wait.
- [V] Independent Luna baseline: 24 composer/editor-filtered tests passed. Full content suite has a pre-existing failing worker-result group: unpaired sender / wrong job / wrong origin expect zero calls but see two. Preserve and report this baseline rather than claiming a clean full suite.

## Plan and checks

1. Read only the exact affected tab's entry attributes and owner/target binding. No prompts, cookies, tokens or page-value capture. Do not expand selectors based on accessibility text alone.
2. Reproduce the confirmed mismatch in a focused offline fixture before fixing it. Use the existing content harness; do not let a fragment-matching mock falsely prove CSS correctness.
3. Repair the shared editor candidate path only, preserving fresh-chat, native image-mode, draft, upload ownership and no-Send guards. Fail closed on ambiguous live editors.
4. Run focused regressions and relevant content/worker suites; distinguish existing failures. Independent review checks selector scope and safety gates.
5. If the queue and cleanup are still empty, safely reload only the extension and verify version/receiver readiness through MCP. Do not restart the owner, submit a preflight/generation, resolve jobs or touch unrelated work. Requester runs its own preflight after readiness is reported.

## Current boundary

No composer repair or live reload has happened yet. Waiting for exact DOM/target evidence. Requester paused its submissions. The earlier queue patch remains local; this task does not authorize activating it.

## Exact live DOM observation

- [V] Independent Luna opened Nba's native View > Developer > JavaScript Console, read only entry metadata, then closed DevTools and restored layout. Path `/`: one visible DIV, no ID, `role=textbox`, `contenteditable=true`, `aria-label=Ask ChatGPT`, closest form present. Two visible SPANs have `contenteditable=false`, no label or role.
- [V] That DIV matches the existing editor selector exactly. A selector-mismatch repair is not justified by current evidence. Next discriminate stale loaded receiver / bound tab mismatch / transient mounting. No selector expansion based on speculation.

## Binding diagnostic plan

- [V] Both locally persisted failed jobs bind tab `1652896704` and stopped in `prepared`. Current compact status exposes only a paired-tab boolean, so it cannot compare this with the current heartbeat tab. Heartbeat metadata is transient; disk cannot prove current binding.
- [V] Earlier browser inventory identified tab `1652896704` as the Settings notifications page in the Chaowaphat Chrome profile, while the observed home composer was in Nba. This is time-qualified evidence of a wrong target, not a fresh confirmation of current binding.
- Reuse the existing heartbeat and status paths; no external project covers this private status gap. Expose the validated paired tab ID, job tab ID, readiness and receiver codes in compact status. Never expose free-form tab errors; report only whether one exists. Preserve queue and receiver behavior.
- Check with focused tests for matching and differing tab IDs, legacy/unpaired defaults and exclusion of sensitive free-form strings. Do not reload, restart, submit, or deploy; local tests cannot verify the live process.
- [V] Local implementation and tests: compact status exposes the paired and job tab IDs, bounded receiver codes and readiness flags, with only error presence for free-form tab errors. Five relevant Python suites passed (351 tests); these changes have not been loaded into the live owner.
