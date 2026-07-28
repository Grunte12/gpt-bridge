# Failure-recovery overlay

- Retry transient transport, rate-limit, or server failures with the same
  prompt. Do not copy raw errors into the prompt. Run `worker doctor` after a
  repeated transport/authentication failure.
- Do not blindly retry invalid-input or moderation failures. Correct the input,
  simplify ambiguous wording, or remove the unsupported element first.
- For a visible defect, name one targeted correction, repeat all invariants,
  and use `worker edit` on the last accepted or latest useful draft.
- If the artifact is too dense, split it into panels, assets, or slides. If text
  remains wrong, remove it from generation and typeset downstream. If identity
  drifts, return to the anchor reference.
- Never append the full attempt history to the next prompt. Keep the stable
  brief plus the current delta only.
- Stop when acceptance checks pass at delivery size. More attempts after that
  can introduce regression without adding value.
