# Changelog

## 0.2.5

- `tail` and `stats` now show *why* a tool call failed, not just that it
  did. MCP tool-error results carry their own explanation in
  `result.content` (the same text a client would show a user), but
  `record()` was only keeping the `isError` flag and throwing that text
  away -- so a failed call showed up as bare `FAILED (tool error)` with
  no way to tell a division-by-zero from an auth failure without going
  to find the raw log some other way. Now captured as
  `tool_error_message` and surfaced in both: `tail` appends it to the
  red trace line, and `stats`'s printed report lists up to 5 real
  failure messages (transport, tool, and proxy errors alike) instead of
  just counts, which matters most exactly when you need it most --
  reading a failed CI run without re-driving the session.

## 0.2.4

- Fixed: `json.loads()` succeeds for any valid JSON value, not just
  objects -- a bare `null`, `42`, `true`, or `[1,2,3]` is valid JSON.
  `ProxySession.record()` assumed a dict and crashed with
  `AttributeError` on anything else. Reproduced for real: a literal
  `null` POST body took down the HTTP proxy's request handler with an
  unhandled exception (the stdio side happened to swallow it silently
  instead of crashing, which isn't correct either -- the entry just
  vanished). Fixed by treating non-dict JSON the same way invalid JSON
  already is: logged as unparsed, not crashing, not silently dropped.
  Covered by both an explicit test for each non-dict JSON shape and a
  Hypothesis property (record() must never raise for any string input).
- README now leads with a real, runnable example (the official MCP
  reference server via npx) instead of a placeholder package name --
  something to actually try in the next 30 seconds, not just look at.

## 0.2.3

- Fixed: SSE event parsing used `str.splitlines()` to find lines within
  an event block, which treats several Unicode control/separator
  characters as line boundaries in addition to `\n`/`\r` (`\x1c`,
  `\x1d`, `\x1e`, `\x85`, `U+2028`, `U+2029`, `\v`, `\f`). A payload
  legitimately containing one of those (a raw U+2028 is valid,
  unescaped, inside a JSON string) got silently mis-split, losing part
  of the payload. Found by property-based testing
  (`tests/test_sse_buffer_fuzz.py`, Hypothesis), not by hand. Fixed by
  splitting on the literal `\n` the parser already normalizes
  everything to.

## 0.2.2

- Added `greenlight --version` / `-V`. Standard CLI convention that
  was just missing until now.

## 0.2.1

- Fixed: `--http` mode crashed with an unhandled exception when the
  target server was unreachable, leaving the client with a dropped
  connection instead of a response. Now returns a clean 502 with a
  JSON-RPC error body, logged as a new `proxy_error` entry type that
  `tail` and `stats` both handle.
- Fixed: SSE event parsing could miss an event if its `\r\n` boundary
  landed exactly across two chunk reads. Bytes were still relayed to
  the client correctly either way; only the logged trace was affected.
- Fixed: the session log's file write wasn't locked against concurrent
  writers. Only matters for `--http` mode, where multiple real client
  connections can call into the logger at once (the stdio proxy only
  ever has one caller). No corruption was actually reproduced, but the
  gap was real and the fix is free.

## 0.2.0

- `greenlight run --http <url>` -- proxy a remote Streamable HTTP MCP
  server, not just stdio. Same session log format either way; `tail`
  and `stats` work on it unmodified.
- `greenlight stats [path] [--json]` -- message counts, latency
  (min/median/max, per method), and a pass/fail verdict. Exits non-zero
  on any failure (transport or tool-level), so it's usable as a CI
  check, not just an interactive summary.
- Validated against a real npx-launched third-party server (the
  official MCP reference server) in addition to the Python fixture used
  in 0.1.0.

## 0.1.0

- `greenlight run -- <command>` -- transparent stdio proxy for MCP
  servers. Relays stdin/stdout exactly, logs every JSON-RPC message to
  a structured JSONL file.
- `greenlight tail [path] [-f]` -- live trace viewer, colorized by
  status (green/yellow/red), both static replay and live-follow.
- Distinguishes transport-level JSON-RPC errors from MCP tool-level
  failures (`result.isError`) -- the latter is not `"error" in msg` and
  is easy to miss if you only check for the obvious kind.
