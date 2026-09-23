# Greenlight - Day 11 notes

## The real adoption wall, and where to stop

The demo server example works in 30 seconds. Pointing Greenlight at
your own real MCP setup means hand-editing `claude_desktop_config.json`
-- inserting `greenlight run --` in front of the existing command,
working out the exact wrapping syntax, then reverting it by hand later.
That gap is the actual friction between "read about it" and "use it,"
more than any missing feature in the proxy itself.

The obvious fix is a command that finds your config and rewrites it for
you, with a matching unwrap to revert. Thought through what that
actually requires before writing any of it, and the honest answer is:
more than this project has needed so far. Every previous fix only ever
touched Greenlight's own log file. Writing to a file a real, currently-
running app depends on to start up is a different risk category --
partial writes, losing fields the parser doesn't recognize, file locks
on Windows, a backup step that turns out not to actually restore
correctly. None of that is hypothetical; it's the standard list of ways
a config-rewriting tool goes wrong, and getting it right means an
atomic write, exact backup/restore, and testing against throwaway
fixtures before it touches anything real.

Decided not to build that part yet. Built the half that's genuinely
safe: `greenlight wrap` finds the config and prints exactly what each
server entry would look like wrapped, and stops there. No write path
exists in the code at all -- not "writes are disabled by a flag," there
is no function that opens the file for writing. That's most of the
value (working out the wrapping syntax yourself, correctly, is the
actual friction) without the failure mode that would make someone's
Claude Desktop stop working.

## A real gotcha found while building it, not after

Claude Desktop on macOS is launched from the Dock or Finder, not a
login shell, and commonly can't see the PATH a terminal would -- a
known, separate way MCP server commands silently fail to start,
independent of anything Greenlight does. A naive suggestion pointing at
a bare `greenlight` command would have reproduced that exact failure
class for anyone who copied it in. Used `sys.executable` (the absolute
path to the interpreter actually running Greenlight) instead, which
resolves correctly regardless of what environment ends up spawning the
child process.

## Verification

Ran it for real against the actual Claude Desktop config already on
this machine, not just synthetic fixtures -- checked the file's mtime
before and after to confirm nothing was written (unchanged), and it
correctly reported no `mcpServers` entry present rather than crashing
or inventing one. Separately, checked only the config's top-level key
names, not its values, since a real config can hold API keys in `env`
blocks -- nothing about this feature needed to look at those.

10/10 tests now, including a new `test_wrap.py` covering the rewrite
logic against hand-built dicts, config discovery against temp
directories (with a way to isolate it from whatever's actually
installed on the machine running the tests -- the first version of this
test broke by accidentally finding this machine's real config), and bad
JSON / missing-`mcpServers` handling.

## Also fixed today

0.2.5's CI was red: a test asserted the exact wording the `mcp` SDK
generates for a raised exception, which isn't stable across SDK
versions (this project pins no upper bound on `mcp`). The extraction
feature itself was never wrong -- only the test's assumption about
SDK-specific wording. Fixed the assertions and added a version-
independent test against hand-crafted results. Also bumped the CI
Node.js version ahead of a deprecation warning GitHub surfaced in the
logs while looking at that failure.

## Status

Still 0 stars, 0 forks, no new issues or PRs. PyPI shows real installs
happening anyway (158 last month) -- someone's using this without ever
visiting the repo, which says the gap right now is discovery, not
quality. `wrap` doesn't change that by itself. What it changes is
whether someone who does find the repo can get from "interesting" to
"running against my real setup" without giving up at the config-editing
step.
