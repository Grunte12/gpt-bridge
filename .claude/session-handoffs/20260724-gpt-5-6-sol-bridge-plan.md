---
type: session-handoff
status: blocked-on-manual-web-slug-verification
project: Grunte12/chatgpt-api
created: 2026-07-24
---

# GPT-5.6 Sol bridge update plan

## Active workspace and ownership

- Workspace: `C:\Users\User\Documents\GitHub\chatgpt-api`
- Fork: `https://github.com/Grunte12/chatgpt-api`
- `origin` is the user's fork; `upstream` is `suphotP/chatgpt-api`.
- Never push to upstream or open an upstream PR. Continue development only in
  the user's fork.
- Current clean HEAD: `147e057 docs: define verified model alias policy`.

## Non-negotiable account boundary

Account capture, login, cookies, bearer tokens, browser requests, and browser
challenges remain wholly manual and user-operated. Do not add, modify, or use
automation that reads, parses, stores, pastes, or replays those materials. Do
not add authentication retries or challenge workarounds.

## What is verified

OpenAI's current developer documentation names the flagship API target
`gpt-5.6-sol`; the `gpt-5.6` API alias routes to it. It also distinguishes
Terra and Luna as separate roles. Source:
https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6

This repository does **not** call the OpenAI API. It bridges ChatGPT Web. The
official API model ID is therefore not evidence that the Web backend accepts
the identical slug. The prior live bridge evidence showed only the `gpt-5-5`
family. Do not guess a Web slug from the ChatGPT UI display label or from the
API documentation.

## Existing alias implementation inventory

- `chatgpt_api/providers/chatgpt/account_info.py`: static supported Web family
  is `gpt-5-5`, `gpt-5-5-thinking`, and `gpt-5-5-pro`.
- `chatgpt_api/api/openai_compat.py`: builds `/v1/models`, resolves effort
  aliases, and validates models against account capabilities.
- `integrations/opencode/`, `apps/bridge-console/`, and
  `apps/character-game/` mirror the advertised aliases.
- Tests live mainly in `tests/test_account_info.py`,
  `tests/test_openai_compat.py`, `tests/test_chatgpt_models.py`, and
  `tests/test_cli.py`.

## Required user-provided verification before code changes

The user must, in their own browser and by their own hands, select GPT-5.6 Sol
and perform the existing manual account-capture workflow. They should provide
only the resulting backend model slug (or a redacted diagnostic containing
`observed_models`), never cookies, headers, tokens, or a raw browser request.

If the Web backend still reports `gpt-5-5`, do not add a `gpt-5-6-sol` Web
alias: update the user-facing documentation only, because the bridge already
addresses the verified backend model.

## Implementation plan after a new Web slug is verified

1. Add the exact verified Web model family while preserving every working
   `gpt-5-5` alias; do not perform a global string replacement.
2. Extend account capability inference, resolver aliases, and `/v1/models`
   output together.
3. Update only affected OpenCode and web-app picker entries.
4. Add unit tests for resolver mapping, account capability gating, and
   `/v1/models`; add a mock-backed integration test for one completion.
5. Run the full suite and a real bridge completion using the verified model.
   The known unrelated Windows test failure is
   `tests/test_crypto.py::test_load_secrets_key_creates_owner_only_key_file`,
   which asserts POSIX mode `0600` on Windows.

Do not adopt GPT-5.6 API-only request fields, Responses API migration, Pro
mode, persisted reasoning, prompt caching, or multi-agent features as part of
this Web-bridge alias update.
