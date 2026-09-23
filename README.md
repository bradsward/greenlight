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

See what your MCP server is actually doing.

![greenlight tail, showing a real session: a normal call, a slow call flagged yellow, and a failed tool call flagged red](examples/demo.gif)

Real trace, from an actual recorded session (`examples/demo-session.jsonl`),
not staged text. Green for a clean success, yellow for a slow-but-fine
call, red for a tool that actually failed.

A transparent stdio proxy for the Model Context Protocol. Point it at
your real server command instead of running that command directly, and
it relays every byte exactly as before, while recording every JSON-RPC
message to a structured log you can watch live or replay.

Right now, if an MCP integration isn't working, you're debugging blind:
no visibility into what got sent, what came back, or why a call failed.
Greenlight exists to fix that.

**Why not [MCP Inspector](https://github.com/modelcontextprotocol/inspector)?**
Different job. Inspector is a UI you drive yourself to manually test a
server in isolation. Greenlight sits transparently in the path of your
*real* client (Claude Desktop, Claude Code, whatever's actually
running) and records what really happened, not what you tried by hand.
It also writes a durable log (`greenlight stats` exits non-zero on
failure, so it runs in CI) instead of a live session you have to be
watching.

## Install

```bash
pip install greenlight-mcp
```

Or from source:

```bash
pip install -e .
```

## Try it right now, no server of your own required

```bash
greenlight run -- npx -y @modelcontextprotocol/server-everything stdio
```

That's the official MCP reference server -- public, free, no config.
In another terminal:

```bash
greenlight tail -f
```

Watch real tool calls come through live. Needs Node.js for the `npx`
part; nothing else.

## Use it for real

Wherever you'd normally configure a server command, wrap it the same
way:

```bash
greenlight run -- npx -y @some/mcp-server
```

instead of

```bash
npx -y @some/mcp-server
```

For a remote Streamable HTTP server, proxy it instead of spawning a
process:

```bash
greenlight run --http http://127.0.0.1:9000/mcp
```

Greenlight prints the local URL to point your client at (the same path
as the target, just on `127.0.0.1:8808` -- see the printed message,
which includes the exact path). Same session log, same `tail`/`stats`
downstream, regardless of which transport produced it.

Every message that passes through gets logged to `./sessions/`. Watch it:

```bash
greenlight tail                 # replay the most recent session
greenlight tail -f              # follow a session that's still running
greenlight tail path/to/log.jsonl
```

Trace output is colorized by status: green for a clean success, yellow
for a slow-but-fine call, red for anything that actually failed --
including MCP tool-level failures (`result.isError`), not just
transport-level JSON-RPC errors, which are a different thing and easy to
miss if you only check for the obvious one. See `notes/day1.md` for why
that distinction mattered enough to write a whole note about it.

Or skip watching it and just get the summary:

```bash
greenlight stats                # message counts, latency, pass/fail
greenlight stats --json         # same thing, machine-readable
```

`stats` exits non-zero if anything failed -- transport error or tool
error -- so it works as a CI check, not just an interactive summary:

```bash
greenlight run -- npx -y @some/mcp-server &
# ... drive a real session against it ...
greenlight stats || exit 1
```

## How it works

`greenlight run` spawns your real server as a subprocess and sits
between it and the real MCP client, relaying stdin/stdout on two
threads. Every line is parsed as JSON-RPC, correlated by request id
(so a response knows its own method name and latency), and written to a
JSONL file. The one rule the whole thing depends on: nothing but the
child process's actual bytes ever reaches Greenlight's own stdout --
logging and UI output only ever go to stderr or to disk. A single stray
print to stdout would corrupt the protocol stream the real client is
parsing.

## Status

- [x] `greenlight run` -- transparent proxy, validated end-to-end against
      a real MCP server (not a mock)
- [x] `greenlight tail` -- live trace viewer, both static replay and
      genuine live-follow (verified separately, not assumed)
- [x] Windows PATH resolution for `npx`-style commands, validated against
      a real third-party npx-launched server (the official MCP reference
      server), not just the Python fixture
- [x] Published to PyPI -- `pip install greenlight-mcp`
- [x] `greenlight stats` -- summary + CI-usable exit code (non-zero on
      any failure, transport or tool-level)
- [x] Streamable HTTP transport (`greenlight run --http <url>`),
      validated end-to-end against a real HTTP+SSE server, not just stdio
- [x] Property-based tested (Hypothesis) against arbitrary chunking of
      the SSE stream -- found and fixed a real Unicode line-boundary bug
      (`str.splitlines()` treats more than `\n`/`\r` as a line break)
      that hand-written test cases hadn't caught
- [x] Fuzzed the JSON-RPC classifier too -- found and fixed a crash on
      any valid-but-non-object JSON (`null`, `42`, `[1,2,3]`), which
      `json.loads()` accepts but a dict-shaped assumption didn't handle
- [x] Failed tool calls show their real error text, not just a red flag --
      `tail` and `stats` both surface the actual message MCP gave for
      the failure, pulled from the same `result.content` a client would
      show a user

## Notes

[`notes/`](notes/) is a running engineering log, not a cleaned-up
retrospective -- what broke, how it was found, why the fix is what it is.
