# ChatGPT Image core

Choose generation for a new visual. Choose edit when a source image, identity,
brand element, layout, or accepted draft must survive the next attempt.

Keep every prompt self-contained and use this contract:

```text
Mode: <mode>
Deliverable: <asset, intended use, and audience>
Canvas: <orientation/aspect ratio, viewpoint, composition, hierarchy>
Background: <opaque scene, native alpha, or frontend transparent asset>
Content: <scene, subject, required components, relationships>
Visual direction: <medium, style, palette, lighting, materials>
Exact text: "<verbatim copy and placement>"
Source roles: <Image 1 is...; Image 2 contributes...>
Preserve: <identity, geometry, objects, colors, copy, or other invariants>
Change: <only the requested delta>
Constraints: <must preserve/include; forbidden extras; no watermark>
```

Omit empty lines. Order information as scene, subject, important details, then
constraints. Preserve detailed user requirements; add only details that
materially improve a vague request. Use short labeled sections instead of one
long paragraph so a failed result can be debugged one requirement at a time.

For multiple variants, use `--count N` (2-10) with one `--output-path` stem.
Use `--level instant` for cheap drafts (max 4), `medium` (default) for normal
stills, and `high` for a hero/final. ChatGPT Web still returns one image per
request. Bridge reuses one conversation: the first call sends the full brief,
later calls send a short "same brief, variant i/N" follow-up, then writes
`stem-01.png` through `stem-N.png`. If a follow-up cannot continue the
session, that variant starts a new conversation with the full brief. Do not
put "generate N images" in the prompt instead of `--count`.

Before generating, write acceptance checks for content, composition, text,
factual correctness, and forbidden elements. After each attempt, compare only
the latest output against those checks. A polished image that communicates the
wrong thing still fails.
