# Greenlight - Day 12 notes

## Making the tool itself speak MCP

Every previous feature answers a human reading a terminal. The gap
that's actually bigger: an agentic coding assistant debugging someone's
MCP integration has no way to see what Greenlight recorded except a
human copy-pasting `tail`/`stats` output back into the chat. That's a
real bottleneck specifically for the audience this project is built
for -- people building and debugging MCP servers with the help of an
agent that itself speaks MCP.

Built `greenlight serve`: the project's own session data, exposed as an
MCP server. Four tools -- `list_sessions`, `get_session_stats`,
`get_failures`, `get_trace` -- so an agent with this added to its own
MCP config can ask "what actually failed and why" as a tool call and
get the same real data `tail`/`stats` would show a human, without
anyone relaying it by hand. `get_failures` and `get_trace` build
directly on the tool-error-message work from a few days ago -- the
whole reason this is useful is that the real failure text is already
sitting in the log, not just an isError flag.

## The dependency-weight decision

Building this meant importing the `mcp` SDK at runtime, not just in
tests. That's a real conflict with something this project has held
onto deliberately since day one: the base install is just `rich`.
Making `mcp` a required dependency would mean every `pip install
greenlight-mcp` -- including the 99% of people who only ever run
`run`/`tail`/`stats` -- pulls in `mcp`'s own dependency tree for a
feature they'll never touch.

Put it behind an optional extra instead: `pip install
greenlight-mcp[serve]`. `greenlight serve` without it fails with a
clear one-line install instruction, not an ugly traceback. Verified
this actually holds, not just assumed it from the pyproject.toml
change -- installed the package into a genuinely clean venv with no
extras and confirmed two things: `serve` fails cleanly with the right
message, and `pip list` afterward shows only `rich` and its own
dependencies, nothing from `mcp`. The base install's minimalism is a
real property of the package now, not just a claim in this file.

## Verification

Same discipline as everything else here: drove a real MCP client
against a real spawned `greenlight serve` subprocess, not a mock,
first by hand (caught my own test script's bug -- it was only printing
the first content block of a multi-block tool result, which looked
like a missing failure until checking `len(r.content)` showed the SDK
splits list returns into one block per item, and the actual data was
always correct). Then wrote `test_serve.py` against a hand-crafted
fixture session log with one clean result, one tool error, and one
transport error, all known values, so every assertion checks an exact
expected number and exact expected message rather than "some plausible
output" -- including the error path, calling a tool against a session
name that doesn't exist and confirming it comes back as a proper
MCP-level tool error with a clear message, not a crash.

12/12 test files passing.

## Status

Still 0 stars, 0 forks, no new issues or PRs. This one doesn't change
that by itself either -- it's a real capability gap closed, not a
distribution move. Next real check: whether anyone actually wires
`greenlight serve` into their own agent's MCP config and it holds up
against a real debugging session, not just this project's own fixture
data.
