# Extension image recovery

Read this only when the native image route is offline, returns an uncertain job
state, rejects a visibly empty composer, or fails while loading an upload.

## Preserve the job before debugging

- `prepared` with no submission receipt means no remote generation is proven.
  Inspect the recorded job and queue before creating a replacement.
- `claimed` or `remote_started` means work exists. Keep the `job_id` and wait.
- `complete` with `image_path` and hash means generation succeeded. Inspect that
  file even when automatic chat cleanup reports `failed`.
- `hub_unavailable` and `upstream_discovery_failed` are transport/discovery
  failures, not evidence that image generation failed. Refresh the LinkHub
  provider index once, then query and wait on the same `job_id`.

Never cross from the project-approved LinkHub route to the direct Extension MCP
as a troubleshooting shortcut. That creates two control paths and makes job
ownership, queue state, and duplicate prevention ambiguous.

## Reload the runtime that actually changed

The unpacked Chrome extension and the local owner service are separate runtime
components.

1. Confirm the image queue is empty before restarting anything.
2. After changing extension source, reload the unpacked extension and refresh
   the paired ChatGPT tab once. Refreshing the tab alone does not load new
   extension code.
3. If the popup then says it is waiting for MCP or returns HTTP 400 while
   LinkHub reports the extension offline, restart the existing owner service;
   do not launch a second `--serve` process. On this installation the service is
   `org.grunte.gpt-bridge-extension` and can be restarted with
   `launchctl kickstart -k gui/$(id -u)/org.grunte.gpt-bridge-extension`.
4. Do not submit until live status again reports paired, extension online, an
   empty queue, and `next_action=submit_via_mcp`.

## Diagnose an empty-composer attachment rejection

When the composer is visibly empty but the Bridge says to remove existing
attachments, treat it as attachment detection evidence rather than adding
browser clicks or clearing unrelated page content. Inspect the content script's
attachment predicate. It should recognize actual file inputs, attachment
previews/remove controls, upload progress, and busy state. A generic visible
`img` selector also matches decorative composer UI and creates a false positive.

After a focused fix, run the extension content tests, commit only the intended
hunk, then reload both runtime components as described above before retesting.

## Validate uploads before submission

Prefer the original validated PNG, JPEG, or WebP when it fits the live schema's
size limit. Avoid creating helper conversions merely to satisfy an assumed
format requirement. If conversion is necessary, strip metadata and open the
result with the same runtime that will upload it before calling LinkHub. A file
that another macOS tool can display may still fail in Pillow while parsing EXIF
or TIFF metadata.

## Lesson from the 2026-10-24 incident

The failure had four layers: the agent bypassed the required LinkHub route; the
skill did not state that the route also applies during troubleshooting; a
generic `img` selector falsely reported a decorative composer image as an
attachment; and source changes were tested before the loaded extension and
owner service were both refreshed. An extra JPEG conversion then introduced a
separate Pillow/EXIF error. The durable fix is the decision path above: one
route, one submission, one job ID, evidence-based recovery, focused code repair,
and explicit runtime reload.
