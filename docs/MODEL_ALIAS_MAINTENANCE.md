# Model Alias Maintenance

This project exposes friendly OpenAI-compatible aliases for verified ChatGPT
Web backend model identifiers. A name displayed in the ChatGPT product UI is
not, by itself, evidence of a usable wire-level model slug.

## Current verified family

The currently verified text-model family is:

- `gpt-5-5`
- `gpt-5-5-thinking` with `standard`, `extended`, and `max` effort aliases
- `gpt-5-5-pro` with `standard` and `extended` effort aliases when the account
  supports them

`GPT-5.6 Sol` is a UI/display name observed by a user, not a verified backend
identifier. Do not add `gpt-5-6`, `sol`, or a similar guessed alias solely from
that display name.

## Safe update checklist

1. Confirm a new backend slug with a user-operated, already configured local
   bridge. Do not automate account capture, login, token handling, or browser
   challenges to obtain that evidence.
2. Confirm one real completion using that exact slug. A model appearing in a
   picker or documentation alone is insufficient.
3. Update the capability constants in
   `chatgpt_api/providers/chatgpt/account_info.py` and the resolver/model-list
   logic in `chatgpt_api/api/openai_compat.py` together.
4. Update every affected integration and user-facing model list, including the
   OpenCode integration and web applications, so they do not advertise an alias
   the server cannot resolve.
5. Add resolver and `/v1/models` regression tests, run the complete test suite,
   and repeat the real completion check.

Unknown model strings are intentionally passed through by the resolver and then
rejected by account capability validation. They must not be silently remapped
to a guessed existing model.
