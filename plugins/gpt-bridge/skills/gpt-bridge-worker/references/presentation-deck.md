# Image-based presentation deck

Create a flattened visual deck: one complete 16:9 image per slide, then combine
the accepted images into one `.pptx`. Tell the user that slide contents are
image-based and not individually editable.

1. Define: `By the end, <audience> should <outcome> because <takeaway>.`
2. Build a cumulative narrative. Give each slide one job and one primary claim.
   Keep the title slide minimal and close by resolving the opening.
3. Establish one visual system for the full deck: palette, typography, imagery,
   margins, footer treatment, and recurring placement. Vary composition without
   changing the system.
4. Write a separate self-contained prompt for every slide. Include:
   `Slide N of M`, the slide's claim, exact visible copy, required visual,
   shared visual-system description, `16:9 landscape`, and no extra text.
5. Generate slides sequentially as `slide-01.png`, `slide-02.png`, and so on.
   Inspect/refine each in an isolated context. Keep visible body copy brief and
   large enough to read when the full slide is shown.
6. Resolve the installed skill directory as `SKILL_DIR`, then assemble:

   ```sh
   python "$SKILL_DIR/scripts/images_to_pptx.py" \
     --out <final.pptx> \
     --title "<deck title>" \
     <slide-01.png> <slide-02.png> <slide-03.png>
   ```

7. Render and inspect every slide with the host's presentation tooling when
   available. Fix illegible text, inconsistent style, cropping, visual drift,
   incorrect facts, or broken narrative. Return only the final `.pptx` and a
   concise validation note to the main agent.
