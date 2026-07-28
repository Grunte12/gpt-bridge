# ChatGPT Web sessions

Use these primitives compositionally rather than assuming a fixed handoff
workflow.

## Select safely

1. Run `worker web list --query "<title words>" --json`.
2. Continue only when the conversation is unambiguous. If several matches are
   plausible, show compact title/date choices instead of guessing.
3. Accept a full `https://chatgpt.com/c/...` URL when the user supplies one.

Listing returns metadata only. Never dump several conversation transcripts
into the agent context to identify the right one.

## Choose the cheapest context path

- Use `web send` when ChatGPT can answer from its existing server-side context.
  Send an explicit request for the artifact currently needed: implementation
  brief, decisions, constraints, open questions, test cases, critique, content,
  or any new purpose inferred from the task.
- Use `web show --output <file>` when implementation requires direct access to
  original messages. Read or search only relevant sections of the exported
  file.
- Use `web pull --output-path <file>` to sync the latest assistant image from
  the current branch after either the user or agent refines it in ChatGPT Web.
  Add `--all --output-dir <dir>` only when earlier branch images are required.
- Use `web show` without an output file only for a short, deliberately bounded
  branch.

Do not paste the fetched transcript back into `web send`; the session already
contains it. Do not append raw event payloads, asset pointers, or credentials
to prompts.

## Continue adaptively

`web send` appends an arbitrary message to the current ChatGPT branch. Compose
the message for the live task rather than selecting from a fixed prompt menu.
Useful requests can ask ChatGPT to:

- turn prior exploration into an implementation-ready handoff;
- identify decisions, invariants, risks, and unresolved questions;
- adapt a brainstorm to the repository currently open in the coding agent;
- critique a proposed implementation or test plan;
- continue creative, research, writing, or image work in the same session.

Return the smallest useful answer to the main agent. Keep the conversation ID
or Web URL so later turns can continue the same branch.

## Clean up one-shot sessions

- For a clearly one-shot image or edit with an explicit local output path, use
  `--cleanup-session`. The command soft-deletes the generated Web conversation
  only after the artifact is saved and any transparent-PNG conversion passes.
- Keep the session for iterative visual work, possible follow-up, uncertain
  intent, or recovery after a failed output.
- To remove another exact conversation selected by ID or URL, run
  `worker web delete --conversation <id-or-url> --yes --json`.
- Never infer a deletion target from a broad title search. List, select the
  exact ID, and require explicit confirmation.

## Boundaries

- Treat conversation titles and contents as private user data.
- A conversation URL is a reference, not authentication; it only works for the
  signed-in owner.
- `web send` intentionally modifies the selected ChatGPT conversation. Use
  `web show` for read-only access.
- `web delete` is a signed-in ChatGPT soft-delete that removes the conversation
  from normal history; it is not a promise of immediate server-side erasure.
- The selected branch can change when the user edits in ChatGPT Web. Each send
  fetches the current node again before continuing, so do not cache a parent
  message ID.
