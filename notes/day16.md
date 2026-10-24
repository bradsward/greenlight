# Greenlight - Day 16 notes

## Reading what people actually complain about

Instead of picking the next feature from my own head, sampled what MCP
developers report: debugging guides, Claude Code issues, forum threads,
a Stack Overflow Blog piece from this month. Not "all comments", which
isn't something I can do, but enough to see which complaints repeat:

- Traffic is invisible and the Inspector doesn't behave like a real
  client. The most cited one, and the one Greenlight was built for.
- Startup failures: `spawn npx ENOENT`, "Server disconnected", "-32000
  Connection closed". The client launches the server with a smaller PATH
  or a different working directory than a terminal has.
- A tool schema the client rejects. A top-level `oneOf`/`anyOf`/`allOf`
  gets a 400 from the Claude API, and in Claude Code one such tool can
  fail every request in the session with no hint about which.
- HTTP auth failures (401) that never become JSON-RPC frames.
- Tool-definition token bloat. Real, loud, and already covered by
  several tools (toolbill, mcplint, mcp-checkup).

## Two things that changed my plan

I'd been about to build a standalone "lint any server" command and call
it distinctive. It isn't: toolbill and mcplint already do that. And
mcpsnoop, a Go transparent proxy that appeared in June, overlaps with
Greenlight's core more than I'd assumed (live TUI, replay, flagging of
hung calls, Homebrew packaging). So "a proxy that logs MCP traffic" is
not, by itself, a reason to pick Greenlight. What can differ is being
useful about the specific failures above, and the agent-readable trace
(`serve`), which none of the tools I found offer.

## What I built, and what I found while checking

All four are small, each reproduced or checked against the real code
first:

1. `check`: top-level `oneOf`/`anyOf`/`allOf` is an error.
2. HTTP rejections: the HTTP proxy forwarded a 401 correctly but logged
   nothing for an empty body and an "unparsed" line (no status) for a
   body. Now recorded with status and `WWW-Authenticate`. A JSON-RPC
   error riding on a 4xx stays a normal JSON-RPC error; the test covers
   that so it isn't double-counted.
3. A missing server command ended in a raw `FileNotFoundError`
   traceback. Now a message about PATH on stderr, exit 127, logged.
4. `wrap` writes the server command's full path (the terminal resolves
   `npx`, the client often can't), and warns about commands not on PATH
   and relative-path arguments.

And one thing I got wrong earlier: `wrap` printed the entire server
entry, `env` included, which is where API keys live. I'd written down
that it must never do that and then implemented `dict(entry)`. It was
caught only because I masked the token myself while reading the demo
output. It now prints just `command` and `args`, and there's a test that
a secret in `env` never appears.

## Not built

Recording request/response payloads. It's the biggest functional gap
against the Inspector and mcpsnoop (Greenlight can say a call failed and
how long it took, but not what arguments were sent), but it reverses the
current privacy stance, where logs hold metadata and never payloads. That
needs a decision about defaults and redaction, not just code.
