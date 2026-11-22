# Output retention plan (2026-11-22)

## Problem

The extension owner kept every job folder forever: `image*.png|jpg|webp`, `input-*`
and `state.json`. From 2026-10-15 to 2026-11-22 that was 883 jobs and 2.6 GB, plus
397 MB in the legacy `worker/images`. No prune code existed. Callers (run, batch,
agents) already copy each image into their own project, so the bridge copy is a
temporary hand-off, not the archive.

## Research (existing patterns)

Sources are vendor docs I know; I did not re-fetch them this session [?].

| Queue | Rule | What we take from it |
|---|---|---|
| RQ | `result_ttl` (default 500 s), `failure_ttl` separate | Payload TTL is separate from the job record |
| Celery | `result_expires` (default 1 day), cleanup by a periodic task | Expire results on a trigger, not on read |
| BullMQ | `removeOnComplete` / `removeOnFail` `{age, count}` | Age-based removal of finished work only |
| systemd-tmpfiles | age-based delete of files in owned dirs | Delete only regular files in folders we own |

No library knows our job states, so none fits as-is. The gap is a small,
state-aware sweep. The file deletion itself is a few `unlink` calls.

## Readers checked

- No-replay and dedupe use only `state.json` fields: `request_id`,
  `request_fingerprint`, `payload_hash`, `delivered`, `phase`. No file reads.
- `claim()` reads `input-*` only for a `queued` normal job. Every path that
  re-queues a terminal job (`collect_only`, `preflight_cleanup_only`) sends
  names and metadata, never bytes. Timeout replacements exist only for jobs
  without images.
- `image_path` after completion is read by `run_image` (same call or a resume
  with the same `request_id`) and by the batch feeder within about 1 s.
- `resolve()` and `_generation_timing()` use `state.json` **mtime** to find the
  latest job. Any rewrite by the sweep must keep the old mtime.

## Rule

1. Inputs: when a job is saved in a terminal state (`complete`, `failed`,
   `interrupted`), delete its `input-*` files. Keep the `images` metadata
   (names, sha256, bytes) because resolve checks names.
2. Outputs: a `complete` job whose cleanup is closed and whose `completed_at`
   is older than the TTL loses its image files. `state.json` stays, with
   `output_status: expired`, `image_path: null`, sha256 and dimensions kept.
3. Default TTL is 7 days. `--output-ttl-days N` or
   `GPT_BRIDGE_OUTPUT_TTL_DAYS=N` changes it. `0` keeps outputs forever.
4. Stale work: a `queued` or `waiting_for_batch` request that was never
   delivered and is older than the TTL becomes `interrupted` with a clear
   "nothing reached ChatGPT" error. Delivered or claimed work is never touched.
5. Never touch: jobs not in a terminal state, jobs with open cleanup, jobs of a
   running batch, symlinks, files outside the exact job folder.
6. Triggers: owner start (`ExtensionQueue` init) and after every completed
   result. Both run under the queue lock.
7. Legacy `worker/images`: delete regular image files older than the same TTL
   when the direct worker starts.

## Caller contract

- Receipts for a complete job add `output_expires_at` and a short
  `output_note`: copy `image_path` into your project; the bridge copy is
  temporary.
- After expiry, `job`/`wait`/`status` return `output_status: expired`, no path.
- `run` with the same `request_id` after expiry returns `done` if `out_path`
  already holds the same sha256, else `failed` with cause `output_expired`
  and `safe_to_retry: false`. It never submits again.

## Checks

- Unit tests for each rule above, including mtime preservation and "never
  touch in-progress work".
- Full `pytest` and the Node extension suites stay green.

## Not done here

- Deleting the bridge copy right after `run` verifies `out_path`. That is a
  stricter pass-through; it is a separate owner choice.
