# Native upload acceptance — 7 November 2026

Research before editing: reuse the existing Playwright offline Chromium harness and the existing content-script readiness gate. Primary references: [Playwright input tests and API](https://github.com/microsoft/playwright/blob/main/docs/src/input.md), [MDN image load readiness](https://developer.mozilla.org/en-US/docs/Web/API/HTMLElement/load_event). A complete image alone can be broken; the existing `complete && naturalWidth > 0` check is appropriate. No replacement upload tool or dependency is needed.

Plan recorded before changes: inspect bounded historical job metadata; exercise actual native File/DataTransfer and attachment DOM in isolated Chromium; change only a verified omission, or add bounded diagnostics if historical cause cannot be established. Preserve the no-send gate.

## Historical evidence [V]

Read only matching local durable `state.json` records, emitting IDs, timestamps, phase, input counts, generic error, and diagnostic-key presence. No prompts, tokens, image contents, filenames, or URLs were emitted. The four dated records relevant to the previous report are below. Date conversion reveals a boundary discrepancy: only three are created in November 1–6 Bangkok; the fourth is November 7 Bangkok (November 6 UTC). Do not repeat the earlier exact-window count as verified.

| Job | Created Bangkok | Inputs | Phase | Observed cause detail |
| --- | --- | ---: | --- | --- |
| 53b9c148e35b4d948a0efcc86e975789 | Nov 1 23:10:41 | 6 | prepared | generic readiness timeout only |
| 141f33fc927b4e2e8040e952efa0415c | Nov 5 14:50:15 | 3 | prepared | generic readiness timeout only |
| a9a2940e717c4b9db1f00648352583b9 | Nov 6 14:16:16 | 5 | prepared | generic readiness timeout only |
| 4cd47e7f3db54278abce97e18dde2d7b | Nov 7 00:15:02 | 5 | prepared | generic readiness timeout only |

All say `Not submitted. Native uploads not verified ready; inspect the unsent draft. Nothing was submitted.` No stored DOM snapshots/readiness diagnostics identify which condition failed. Their exact historical causes remain unknown; neither UI drift nor slow upload is established. Undated, older and preflight records were excluded from these four.

## Change and checks [V]

The readiness timeout now appends bounded counts (`expected`, `cards`, `removes`, `loaded_thumbnails`) and a `pending` boolean. It includes no filenames, URLs or composer text. Original prefix remains compatible with inspected cleanup handling. Ownership, composer identity, order, exact filename, loaded thumbnail, Remove, progress/error and foreign attachment checks are unchanged. There is no optimistic submission or automatic cleanup/retry.

- `node --test tests/extension_content.test.cjs`: 201 passed.
- `tests/extension_native_upload.chromium.test.cjs`: four offline scenarios passed on real Chrome 156.0.8078.80: ready, missing decoded thumbnail, pending progress, reversed cards. Ready preflight succeeds; all other cases fail closed with diagnostics. No clicks and zero live network requests. The failing-case clock is accelerated; the production 15-second deadline is unchanged.
- `git diff --check`: passed.

Reproduce using the existing Playwright test installation, or set `PLAYWRIGHT_MODULE=/Users/grunte/Workspace/repos/shopkud/node_modules/playwright` and `CHROMIUM_EXECUTABLE=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, then run `node --test tests/extension_native_upload.chromium.test.cjs`. The first restricted launch aborted; the isolated launch with approved execution passed.

Limitations: ChatGPT page behavior and Chrome runtime messaging are fixtures; native DOM, File/DataTransfer and image decoding are real. No live browser profile, real jobs, reload, deployment, generation, or historic draft was touched. This proves the local safety boundary, not current ChatGPT compatibility or the cause of the four historical failures.
