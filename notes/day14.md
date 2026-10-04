# Greenlight - Day 14 notes

## The adoption path was broken

Tried the exact flow the README sells -- `greenlight wrap`, paste the
result into a real client config -- from the client's point of view
instead of a terminal's. Logs went to `Path.cwd() / "sessions"`, and the
working directory belongs to whoever launches the process. Claude
Desktop on macOS commonly launches MCP servers with cwd `/`. Reproduced
with a read-only cwd: `PermissionError` from `mkdir`, before the real
server was ever spawned. So the most likely first real use of this tool
broke the user's server outright -- the one thing a transparent proxy
must never do. And even with a writable cwd, the log landed somewhere
`greenlight tail` in a terminal would never look.

Fix is two separate decisions:

1. A fixed default, `~/.greenlight/sessions`, with `--log-dir` and
   `$GREENLIGHT_SESSIONS_DIR` overrides. Every command resolves it the
   same way, so `tail` finds what the client-launched proxy wrote. HOME
   is in the minimal environment MCP clients pass to servers (checked the
   SDK's own `DEFAULT_INHERITED_ENV_VARS`: HOME on POSIX, USERPROFILE on
   Windows), so this resolves under a real client, not just a terminal.
2. A log location that can't be written is now a warning, not a crash.
   The proxy relays unrecorded. Losing a trace is our failure; failing to
   start someone's server is theirs, and they didn't sign up for it.

Test uses a log dir whose parent is a regular file -- unwritable for
root too and on Windows, unlike chmod tricks.

## Found a second bug while verifying the first

The read-only-cwd reproduction hung after printing the relayed message.
Checked master: `echo '{...}' | greenlight run -- cat` never exits. The
stdin pump never closed the child's stdin when the client's stdin hit
EOF, so the server never saw EOF. That EOF is the MCP stdio transport's
shutdown signal, so every clean client shutdown hit this -- clients
eventually SIGTERM, which is presumably why nobody noticed. One-line fix
(close the destination when the client->server pump ends), regression
test with a Python echo server so it runs on Windows too.

## greenlight check

The `unparsed_lines` count has been sitting in `stats` output as a dim
footnote since day 3. It's actually the single most common stdio MCP bug
-- a server printing to stdout -- and it doesn't fail any call, so
`stats` never flagged it. `check` is the command for that class of bug:
things wrong with the server that don't look like failures. Stdout
pollution, tool definitions (missing/non-object `inputSchema`, duplicate
names, missing descriptions, names outside `^[A-Za-z0-9_-]{1,64}$`),
unanswered requests, orphan responses, very slow calls.

Needed two more fields in the log: the JSON-RPC `id` (so pairing works
after the fact, not just in the proxy's in-memory map), and for
`tools/list` results a summary of each tool. Deliberately a summary --
name, description, schema presence/type -- not the full schema or any
tool call params, so logs don't start carrying user data they didn't
before.

Tested against `tests/bad_fixture_server.py`, hand-rolled because the
SDK won't let you make most of these mistakes, recorded through the
real proxy: exactly the seven expected finding codes, nothing else. The
clean demo session produces zero findings.

## Distribution

`uvx greenlight-mcp` now works (added a `greenlight-mcp` script alias --
uvx runs the command named after the package). Most MCP configs in the
wild use `npx`/`uvx`, and "pip install first" is a step people skip.
README rewritten around that: try it in one command, then the real
config, then the commands. The development checklist moved out; the
changelog already has that history.

## Verification

16/16 test files passing locally in a fresh venv. `test_npx_server`
failed on its first run in this sandbox: the MCP client's minimal child
environment strips the sandbox TLS proxy's CA settings, so npm couldn't
fetch the package. Passed once npm's cache was warm. That's a property
of this sandbox, not the code.

## Status

Still 0 stars. Days 12-13 picked features over outreach, twice. The
fixes above had to come first -- promoting a tool whose real-client path
crashed would have burned the attention -- but the next step is getting
it in front of people, not another feature.
