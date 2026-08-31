# Greenlight - Day 8 notes

## Closed the gap between source and published package

Three real fixes from the last session (unreachable target, SSE CRLF
boundary, concurrent write lock) existed only in source, not in the
0.2.0 release on PyPI. Bumped to 0.2.1, rebuilt, and before calling it
done, actually installed the built wheel into a throwaway venv and
checked `greenlight.__version__` against it.

It said 0.1.0.

## The version string bug

`__init__.py` had `__version__ = "0.1.0"` hardcoded since day one.
Every version bump since (0.2.0, then 0.2.1) updated `pyproject.toml`
but not this file, because nothing ever pointed at it and nothing ever
checked it. It's the same category of gap as the CRLF chunk-boundary
bug: fine on the happy path, wrong the moment anything actually
depended on the value being correct. Fixed by deriving it from
installed package metadata (`importlib.metadata.version`) instead of
maintaining a second hand-written copy of a fact that already exists
in `pyproject.toml`. Can't drift again because there's nothing left to
keep in sync.

Found this specifically because "did I actually verify the built
artifact, not just that the build command exited zero" is now a
standing habit from the last several releases, not a one-off check. It
paid off again.

## Also added: --version / -V

Noticed while fixing the above that the CLI never had this at all --
about as standard a convention as a CLI has, and it was just missing.
Small, but it's the kind of gap that's invisible until someone goes
looking for it, same as the CI badge and the demo GIF placement earlier.

## Three patch releases in one sitting, not one

0.2.1 (the three bug fixes) got tagged and released before the
`--version` idea came up. Rather than quietly editing an already-tagged
release, bumped again to 0.2.2 for it. A tag should mean what it says
it means.

## Property-based testing found a real bug, on the first run

Added Hypothesis to fuzz consume_sse_buffer (the SSE event-boundary
parser from issue #3) -- the property being checked: for any sequence
of events and any way of chunking the resulting byte stream, every
event is recovered, in order, uncorrupted. This directly generalizes
the manual regression test for issue #3 (one specific chunk split)
into an exhaustive-ish check across hundreds of generated splits per
run.

First run found a real bug that hand-written tests had missed:
event.decode().splitlines() doesn't just split on \n and \r --
Python's splitlines() also treats \x1c, \x1d, \x1e, \x85, U+2028,
U+2029, \v, and \f as line boundaries. A payload containing a raw
U+2028 (valid, unescaped, inside a JSON string) got silently mis-split,
losing part of the payload, even though the actual \n-based event
framing was already correct at that point. Fixed by splitting on the
literal "\n" the function already normalizes everything to
(str.split("\n")), not Python's broader definition of a line.

Worth being honest about what this demonstrates and what it doesn't:
this isn't "I am extremely rigorous and thought of everything." It's
"a machine trying thousands of inputs found something a human checking
a handful of cases by hand didn't," which is a real, specific
argument for using this technique, not a character trait to claim
credit for.

## Extending the same fuzzing to the other proxy path

The SSE fuzz test only covered the HTTP proxy's event-boundary parser.
The stdio proxy's ProxySession.record() has its own JSON-handling logic
and had never been fuzzed. Worth checking, since json.loads() succeeds
for any valid JSON value, not just objects -- a bare "null", "42",
"true", or "[1,2,3]" all parse fine, and record() immediately called
msg.get("id") on the result, assuming a dict.

Reproduced for real before fixing, same as always: sent a literal
`null` POST body through the live HTTP proxy. It crashed the request
handler with an unhandled AttributeError -- the client got a dropped
connection, same failure shape as the original unreachable-target bug.
Checked the stdio side too: its caller happens to wrap record() in a
bare except, so there it doesn't crash the process, but the entry
silently vanishes instead of being logged -- not the right behavior
either, just a quieter wrong one.

Fixed at the source (inside record() itself, not at each call site),
so both the HTTP and stdio paths are protected by one fix instead of
two. Covered two ways: an explicit test enumerating each non-dict JSON
shape (7 cases), and a Hypothesis property generalizing to "record()
must never raise for any string input, JSON or not" -- 300 generated
examples, matching the same fuzzing discipline as the SSE parser.

## Also: a real onboarding friction point, unrelated to any bug

Noticed while thinking about what actually drives adoption, not just
correctness: the README's usage example used a placeholder package
name (`@some/mcp-server`). A visitor with curiosity but no MCP server
of their own had no way to actually try Greenlight in the next 30
seconds. Replaced the lead example with the real, public, official MCP
reference server via npx -- verified it actually works standalone with
zero configuration before putting it in the README, not just assumed
it would.

## Status

v0.2.2 tagged and released on GitHub, CI green on both platforms at
every step along the way. v0.2.3 (splitlines fix + SSE fuzz) and 0.2.4
(record() crash fix + record() fuzz + README onboarding fix) -- see
the commits for exact status of each. None of 0.2.1 through 0.2.4 are
on PyPI yet -- needs the maintainer's token from their own terminal,
same constraint as every release before this one. Built, twine-checked,
and wheel-verified either way, so publishing is one command whenever
that happens.
