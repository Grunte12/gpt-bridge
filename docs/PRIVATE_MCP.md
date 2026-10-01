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

Jobs run one at a time, expire after 90 minutes, and have a 100-job per-process
limit. Job IDs are in memory: restarting the server loses job lookup, but files
remain in the data directory. Cancellation stops the local worker; already
submitted ChatGPT work may still finish. Raw stderr stays local and is excluded
from remote artifacts. No timing or model-token savings percentage is claimed;
measure comparable tasks in the target client.

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

Stdio uses the client's local process boundary. HTTP requires the bearer token
even over Tailscale. Use CLI locally when your host already supports it; MCP is
an additional adapter, not a replacement.
