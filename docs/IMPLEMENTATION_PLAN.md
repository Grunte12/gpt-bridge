# GPT Bridge — current implementation plan

Updated: 2026-07-25

## Completed foundation

- Unified the prior local bridge and worker workflow under GPT Bridge.
- Added the canonical `gpt-bridge` command and retained legacy aliases only for
  compatibility.
- Built encrypted local account administration, loopback-only Docker defaults,
  restrictive CORS, authenticated artifact downloads, local Console, worker
  threads, model fallback, reports, image, and research workflows.
- Added consent-based visible-browser onboarding with manual login/MFA/challenge
  handling and a copied-request fallback.
- Removed the discontinued demo application and its Docker/profile/screenshot
  references.
- Added public security, disclaimer, provenance, release-checklist, and handoff
  documentation.

## Current priorities

1. **Reliability:** keep provider-facing behavior behind regression tests; test
   a real user-owned capture manually only when a change needs it.
2. **Onboarding clarity:** keep the Docker setup, Console, `auth login`, and
   manual capture fallback understandable for non-technical local users.
3. **Compatibility discipline:** retain necessary internal names/routes and
   legacy command aliases without presenting them as the public product.
4. **Release hygiene:** maintain documentation, dependency/provenance review,
   secret scanning, plugin validation, and Docker verification.

## Explicitly out of scope

- hosted SaaS, public API hosting, LAN defaults, multi-tenant accounts,
  credential sharing, resale/billing, stealth browser automation, CAPTCHA/MFA
  bypass, or attempts to evade provider limits.
- a fixed HTML-report template: report output stays model-authored and must be
  treated as untrusted active content.

## Done means

For a user-facing change: README and relevant guide updated; Console and CLI
wording agree; tests cover the behavior; `python -m pytest -q`, Console
check/build, plugin validation, `docker compose config`, `git diff --check`,
and (when relevant) an authenticated local Docker check pass.

See `docs/HANDOFF.md` for exact current state and `docs/RELEASE_CHECKLIST.md`
for commands.
