# Private MCP for remote agents

Keep using the CLI for local coding agents. The optional MCP adapter exposes
the same worker to Muse or other clients through a private Tailscale connection.
It needs no Docker. The caller's runtime must already be on your tailnet.

## Install and run

```bash
uv pip install --python .venv/bin/python -e '.[mcp]'
gpt-bridge-mcp --transport http --account main \
  --allowed-host macbook.your-tailnet.ts.net
```

The server generates a private token file at
`~/.local/share/gpt-bridge/mcp/access-token` (mode 600), without printing its
value. Alternatively supply `GPT_BRIDGE_MCP_TOKEN` or `--token-file`.
The server listens only on `127.0.0.1:8766`. Publish it privately:

```bash
tailscale serve --bg http://127.0.0.1:8766
```

Use `https://macbook.your-tailnet.ts.net/mcp` in the client with header
`Authorization: Bearer <private random token>`. This adapter supports
Streamable HTTP and bearer authentication, not OAuth-only or legacy SSE clients.
Tailscale Serve stays within your tailnet; do not enable Funnel. Restrict tailnet
access to the intended caller using Tailscale grants/ACLs. Each server instance
has one explicit ChatGPT account; credentials remain local.

## Token-free Tailscale mode

For a personal tailnet where every permitted device should have access:

```bash
gpt-bridge-mcp --transport http --account main --auth tailscale \
  --allowed-host macbook.your-tailnet.ts.net
tailscale serve --bg http://127.0.0.1:8766
```

Connect to the same HTTPS `/mcp` URL without an Authorization header. The
adapter checks the loopback proxy, exact hostname, and Serve's
`Tailscale-User-Login` header; it rejects missing identity and Funnel requests.
Serve removes caller-supplied identity headers before adding its own.
See [Tailscale's identity-header documentation](https://tailscale.com/docs/features/tailscale-serve#identity-headers).

Keep the backend on loopback and do not enable Funnel. Local processes are
trusted and can impersonate these headers. Tailnet grants/ACLs decide which
devices can reach Serve. Tagged nodes without a user identity should use the
default bearer mode instead. This mode neither reads nor generates a token.

## Agent instructions (on demand)

Only three tools are advertised: `search_tools`, `call_tool`, and `job_status`.

1. Search with a short task description. Results omit schemas by default.
2. Search the chosen name with `detail="schema"` to obtain its arguments.
3. Invoke `call_tool(name, arguments)`. Long work returns a job ID immediately.
4. Use `job_status(job_id, wait_seconds=30)` instead of frequent polling.
5. Read only necessary text via `artifact.read`; download binary artifacts
   directly over authenticated HTTP using their returned `download_path`.
   A local filesystem path alone is not accessible to a remote agent.

Generation/editing retain the worker's compact responses, alpha processing,
and optional `cleanup_session`. Prepare prompts in the caller; use editing for
targeted refinements. ChatGPT Web continuation uses its existing server-side
context rather than replaying a transcript. Automatic conversation deletion
is opt-in; destructive account/admin endpoints are not exposed.

Jobs run one at a time, have a 90-minute execution timeout, and at most 100
active/queued jobs. Compact job metadata is saved atomically with private
permissions. After restart, completed job IDs and artifacts remain readable;
unfinished jobs become `interrupted`, never automatically replayed. Inspect
artifacts and ChatGPT history before retrying interrupted work. Metadata and
artifacts are retained on disk; there is no automatic retention cleanup yet.
One server per data directory is enforced on macOS/Linux.
Cancellation stops the local worker; already
submitted ChatGPT work may still finish. Raw stderr stays local and is excluded
from remote artifacts. No timing or model-token savings percentage is claimed;
measure comparable tasks in the target client.

## macOS service (operator setup, not an agent tool)

Stop any manually running server on port 8766 before installation:

```bash
gpt-bridge-mcp-service install --account YOUR_ACCOUNT \
  --allowed-host macbook.your-tailnet.ts.net
gpt-bridge-mcp-service status
gpt-bridge-mcp-service restart
gpt-bridge-mcp-service stop
```

This installs one user LaunchAgent, starts it at login, and restarts it after
exit. It requires a logged-in macOS user; it is not a boot-time system daemon.
Mac sleep/offline still makes the endpoint unavailable. `stop` unloads the
service now but leaves the plist for the next login. To change account/host,
rerun `install` with explicit `--replace`. No credentials are put in the plist.
Workspace access stays disabled. Service logs stay in the private data
directory. The service does not enable Tailscale, alter DNS/routes, configure
Serve, or install anything inside Muse.

`GET /healthz` uses the same authentication as `/mcp` and reports server
readiness and active jobs only. `provider_verified=false` is intentional:
server health does not prove that a saved ChatGPT session still works.
Use local `gpt-bridge account-check --account YOUR_ACCOUNT` separately.

For hosted agents, verify their supported private-network integration before
joining a tailnet. Do not change a managed runtime's DNS/default route just to
reach this endpoint. If private connectivity is unsupported, this deployment
cannot be reached by that client; do not make it public as a workaround.

## Optional workspace tools

```bash
gpt-bridge-mcp --transport http --account main \
  --allowed-host macbook.your-tailnet.ts.net \
  --workspace /absolute/path/to/one/repo \
  --test-commands /absolute/path/to/test-commands.json
```

The workspace tools read bounded text and replace exactly one matching text
occurrence. Traversal, escaping symlinks, hidden directories/files, account and
secret directories are excluded. Configure a project folder rather than a home
directory. Only fixed test command names can run; there is no remote shell.
Test commands execute project code with the server user's permissions, so
enable them only for callers/projects you authorize.

Example operator-owned test configuration:

```json
{"unit": ["/absolute/path/to/repo/.venv/bin/python", "-m", "pytest", "-q"]}
```

## Local stdio clients

```json
{"mcpServers":{"gpt-bridge":{"command":"gpt-bridge-mcp","args":["--account","main"]}}}
```

Stdio uses the client's local process boundary. HTTP defaults to bearer auth;
token-free mode requires Tailscale Serve as described above. Use CLI locally when your host already supports it; MCP is
an additional adapter, not a replacement.
