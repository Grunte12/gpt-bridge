# Reference, edit, and consistency overlay

- Use `gpt-bridge worker edit`, not a fresh generation, when identity, product
  geometry, brand, composition, or an accepted draft must persist.
- Number inputs in prompt order: `Image 1 = identity/reference`, `Image 2 =
  garment`, `Image 3 = environment`, and state exactly what each contributes.
- Separate three lists: `Preserve`, `Change`, and `Forbidden changes`. Say
  “change only…” and repeat every important invariant on each retry.
- For people, preserve facial identity, age, body proportions, skin tone, hair,
  and distinguishing features unless the user requests otherwise.
- For composites, specify scale, occlusion, pose, contact, lighting direction,
  shadow, perspective, and interaction between sources. Do not request a loose
  collage unless that is the intended output.
- Make one targeted delta per corrective edit. If drift begins, return to the
  last accepted source instead of editing a degraded descendant.
