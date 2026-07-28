# Frontend or website asset

Use this guide for transparent raster assets that enrich an implemented
frontend: hero foregrounds, mascots, product cutouts, organic ornaments,
illustrated scene fragments, stickers, overlays, or decorative clusters.

- First decide whether a raster asset is justified. Keep text, controls, logos,
  simple icons, gradients, geometric shapes, and responsive layout in
  HTML/CSS/SVG so they remain sharp, accessible, and editable.
- Define the asset's role, DOM layer, target CSS size, device-pixel ratio,
  aspect ratio, focal anchor, safe padding, overlap behavior, light/dark
  backgrounds, and whether it is semantic or decorative.
- Generate at roughly 2× the intended CSS dimensions when possible. Keep the
  subject away from canvas edges and forbid embedded copy, UI controls,
  checkerboards, frames, mock browser chrome, and unrelated scenery.
- Save a stable kebab-case filename under the project's normal asset directory.
  Use `.png` and `--transparent`; success means the CLI verified real alpha or
  safely removed a flat generated matte:

  ```sh
  gpt-bridge worker image \
    --prompt "<self-contained asset specification>" \
    --output-path src/assets/generated/<asset-name>.png \
    --transparent \
    --brief
  ```

- Inspect the PNG over both light and dark backgrounds at actual delivery size.
  Reject opaque corners, checkerboard pixels, bright halos, color spill,
  clipped edges, excessive empty canvas, and blurry detail.
- Integrate with intrinsic `width` and `height` to avoid layout shift. Give
  meaningful assets concise alt text; use empty alt text for decoration. Keep
  decorative overlays non-interactive and out of the accessibility tree.
- Preserve the source PNG. Optimize a delivery copy only with tooling that
  retains alpha. Do not inline large images as base64.
- For a coordinated asset pack, also read
  `references/risks/batch-series.md`. For a correction or variant, use
  `worker edit --transparent` from the accepted asset instead of regenerating
  identity and style from zero.
