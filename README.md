```
  .-----.
  |  🔴  |
  |  🟡  |
  |  🟢  |
  '-----'
   greenlight
```

# greenlight

[![PyPI](https://img.shields.io/pypi/v/greenlight-mcp)](https://pypi.org/project/greenlight-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/greenlight-mcp)](https://pypi.org/project/greenlight-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![tests](https://github.com/bradsward/greenlight/actions/workflows/tests.yml/badge.svg)](https://github.com/bradsward/greenlight/actions/workflows/tests.yml)

Listed in [awesome-mcp-devtools](https://github.com/Epistates/awesome-mcp-devtools#development-tools).

**See what your MCP server is actually doing.**

![greenlight tail, showing a real session: a normal call, a slow call flagged yellow, and a failed tool call flagged red](examples/demo.gif)

When an MCP integration misbehaves, you're usually debugging blind: the
client says a tool "failed" or quietly never calls it, and you can't see
what was sent or what came back. Greenlight is a transparent proxy that
sits between your real client (Claude Desktop, Claude Code, Cursor,
Windsurf) and your real server, relays every byte unchanged, and records
every JSON-RPC message so you can watch it live, replay it, or lint it.

- **`tail`**: a live, color-coded trace. Green means ok, yellow means slow,
  red means failed, and failed calls show the tool's real error message.
- **`check`**: catches server bugs that never show up as a failed call,
  like printing to stdout, broken tool schemas, or requests that never got
  a response.
- **`stats`**: a summary with a CI-friendly exit code.
- **`serve`**: exposes the trace as an MCP server, so your coding agent
  can read the failures itself.

## Try it in 30 seconds

```bash
uvx greenlight-mcp run -- npx -y @modelcontextprotocol/server-everything stdio
```

Then, in another terminal:

```bash
uvx greenlight-mcp tail -f
```

That's the official MCP reference server, with nothing to configure. It
needs [uv](https://docs.astral.sh/uv/) and Node.js. Prefer pip?
`pip install greenlight-mcp`, then use `greenlight` wherever this README
says `uvx greenlight-mcp`.

## Use it with your real client

Wrap the server command in your client's MCP config:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["greenlight-mcp", "run", "--name", "my-server", "--",
               "npx", "-y", "@some/mcp-server"]
    }
  }
}
```

Or let Greenlight write the snippet for you:

```bash
greenlight wrap
```

`wrap` finds your Claude Desktop, Claude Code, Cursor, or Windsurf config
and prints each server entry rewritten to run through Greenlight. It's
read-only and never edits the file. Its output uses an absolute Python
path, which also avoids the common "client can't find `uvx`/`npx` on its
PATH" startup failure (Claude Desktop on macOS doesn't see your shell's
PATH).

Logs go to `~/.greenlight/sessions/`, whichever directory the client
launched the server from. To put them somewhere else, use `--log-dir` or
set `GREENLIGHT_SESSIONS_DIR`. If the log directory can't be written,
Greenlight warns on stderr and keeps relaying. It never stops your server
from starting.

For a remote Streamable HTTP server, proxy the URL instead:

```bash
greenlight run --http http://127.0.0.1:9000/mcp
```

Point your client at the local URL it prints. You get the same logs, and
the same `tail`, `check`, and `stats`.

## Commands

```bash
greenlight tail            # replay the most recent session
greenlight tail -f         # follow a live session
greenlight check           # lint the session for protocol/server bugs
greenlight stats           # counts, latency by method, pass/fail
```

### `check`: bugs that don't look like failures

```
$ greenlight check
  error   stdout-pollution  server wrote 1 non-JSON-RPC line(s) to stdout, e.g. 'server starting up...'.
          In the stdio transport stdout is for protocol messages only -- send logs and prints to stderr.
  error   tool-no-input-schema  tool 'no_schema' has no inputSchema -- the spec requires one, even for
          a tool with no arguments ({"type": "object"})
  error   tool-duplicate-name  tool name 'ok_tool' appears more than once in a single tools/list response
  warning unanswered-request  'tools/call' (id 3) never got a response from the server
  warning tool-no-description  tool 'no_description' has no description -- the model picks tools by
          description, so it may never call this one
  ...
```

Real output, abridged, from [`tests/bad_fixture_server.py`](tests/bad_fixture_server.py),
a server built to make these mistakes on purpose.

It also flags non-object input schemas, tool names some clients reject,
responses to ids nobody sent, and very slow calls. Errors exit non-zero,
and so do warnings with `--strict`. `--json` gives machine-readable
output.

### CI

Both `check` and `stats` exit non-zero on failure. `stats` fails on tool
errors (`result.isError`) as well as JSON-RPC errors. That matters
because a failed tool call arrives as a *successful* JSON-RPC response,
and it's easy to miss if you only check for the obvious kind:

```bash
greenlight run --log-dir ./trace -- python my_server.py < scripted_session.jsonl
greenlight check --log-dir ./trace && greenlight stats --log-dir ./trace
```

### `serve`: let your agent read the trace

```bash
pip install "greenlight-mcp[serve]"
greenlight serve
```

Add `greenlight serve` to your coding agent's MCP config, and it can call
`get_failures`, `get_problems`, `get_trace`, or `get_session_stats`
itself. It sees the real error messages, so you don't have to paste
terminal output.

## Why not MCP Inspector?

They do different jobs. [Inspector](https://github.com/modelcontextprotocol/inspector)
is a UI you drive by hand to test a server in isolation. Greenlight sits
in the path of your *real* client and records what actually happened in a
real session. That includes the client's exact requests, which is usually
where the bug turns out to be. It also leaves a durable log you can check
in CI.

## How it works

`greenlight run` spawns your server as a subprocess and relays
stdin/stdout on two threads. It parses each line as JSON-RPC, correlates
each response with its request by id (so every response knows its method
and latency), and appends the result to a JSONL file. The one rule
everything depends on: nothing but the server's own bytes ever reaches
Greenlight's stdout. Status output goes to stderr, and logs go to disk.

The base install depends only on `rich`. Python 3.10+, tested on Linux
and Windows.

## More

- [CHANGELOG.md](CHANGELOG.md): what changed in each release.
- [`notes/`](notes/): a running engineering log of what broke, how it
  was found, and why each fix is what it is.
- Issues and PRs welcome. If Greenlight misreads a real session, the log
  file is the most useful thing you can attach.
