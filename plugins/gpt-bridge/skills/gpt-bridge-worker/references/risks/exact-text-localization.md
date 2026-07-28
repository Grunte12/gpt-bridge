# Exact text and localization overlay

- Finalize translation, spelling, punctuation, line breaks, capitalization, and
  legal wording before image generation. The image model is not the translator
  or source of truth.
- Put every visible string in quotes. Use ALL CAPS or spell difficult names
  letter by letter when that improves fidelity. State location, hierarchy,
  alignment, and whether any other text is forbidden.
- For localization, edit the accepted source and say: replace only the quoted
  copy; preserve layout, images, colors, logo, hierarchy, and all non-text
  elements. Allow text-box resizing only if needed for expansion.
- Inspect at full resolution and verify every character, number, unit, URL, and
  reading order. One wrong glyph fails the asset.
- If exact copy remains unreliable, generate the visual without text and add
  type with deterministic layout tooling.
