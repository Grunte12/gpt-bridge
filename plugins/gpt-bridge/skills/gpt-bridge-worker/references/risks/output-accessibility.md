# Output and accessibility overlay

- State final use, aspect ratio, orientation, minimum readable size, focal safe
  zone, edge clearance, and whether later cropping is expected.
- Require sufficient foreground/background contrast. Do not encode meaning by
  color alone; add shape, icon, pattern, position, or label redundancy.
- Avoid essential detail at the crop edge and avoid tiny text. Inspect the
  asset at its actual delivery size, not only zoomed in.
- For a transparent PNG, use `worker image|edit --transparent` with an explicit
  `.png` output path. The CLI verifies real alpha and safely keys a flat matte
  only when needed; it refuses a complex background instead of damaging the
  asset. Never accept a rendered checkerboard as transparency.
- RGB image output is not proof-ready CMYK. For print, add bleed and safe-area
  requirements, then use downstream prepress tooling.
- After acceptance, provide concise alt text or a content summary when the
  destination supports it.
