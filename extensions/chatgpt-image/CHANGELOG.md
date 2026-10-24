# GPT Bridge Image Worker changes

## 0.1.36 — 2026-10-23

- Dedicated-profile single-tab recovery authenticates silently, then reports the final rebound state. It no longer exposes a temporary `confirm_second_tab` action while recovering.

## 0.1.35 — 2026-10-23

- Pairing inspects the selected ChatGPT tab without navigating, then uses the existing guarded preparation helper to open a fresh chat when needed and select native Create image. It never submits a prompt.
- Pairing cleanup uses only the bridge-saved exact chat in a separate inactive tab. The selected composer stays untouched until cleanup is confirmed; then it prepares fresh Create image without claiming or sending a replacement.
- The popup now explains that it prepares the image composer after account confirmation.
