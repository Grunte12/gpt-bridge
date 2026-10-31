# OpenCLI connection findings

Inspected the installed Chrome Web Store Extension 1.0.26 and installed CLI
daemon-lifecycle code. Upstream documentation/source was used for comparison:

- https://opencli.info/docs/guide/browser-bridge.html
- https://github.com/jackwener/OpenCLI/blob/main/extension/src/background.ts

## Observed static implementation

The installed Extension probes a local daemon, connects with WebSocket, sends
a persistent profile context ID/version handshake, and schedules reconnects.
Installed CLI lifecycle code starts the daemon on demand. These mechanics do
not require a popup pairing click. Account login remains in Chrome; routing a
browser profile is distinct from independently identifying a website account.

REA inspected the installed Extension's manifest and background bundle as inert
text, not executed code. Evidence:
`ev_27abd1361ab3eb5e3b34f6a8630b8785391626b9cfe92d0af0757aaf263b3df4`.
Artifact SHA-256:
`32c5b500efbf8167436b408caef531c0de7addd4d96703bcb275ff19b7ff0b65`.
Four other inventoried files were outside selected analysis. Graph coverage is
partial; static checks do not prove runtime authorization or reachability.
Full local evidence: `/tmp/opencli-extension-rea-verified.json` (temporary).

## GPT Bridge design choice

Reuse automatic lifecycle/reconnect and stable ownership, not OpenCLI's broad
browser/cookie permissions. Keep existing Native Messaging authorization and
the deterministic image workflow. Auto-connect opens a separate work tab in
the same Chrome profile; does not inspect arbitrary chats or export credentials.
Repeated failures reuse the same owned tab. Existing jobs or deliberate
disconnect prevent automatic rebinding. Login/challenge failures remain visible.

Node VM tests cover zero-click startup, repeated startup/failure, blocked queue,
and deliberate disconnect. These are simulations, not a live Chrome proof.
Chrome Web Store publishing is separate and has not been performed.
