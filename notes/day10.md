# Greenlight - Day 10 notes

## The one thing a failed tool call couldn't tell you

Went looking for a real gap rather than a cosmetic one. Found it by
re-reading `render.py`'s failure line for `tool_error` next to the one
for transport-level `error`: the transport case prints the actual
message (`FAILED: {message}`), the tool-error case just prints
`FAILED (tool error)` and stops. No message, because `record()` never
kept one -- only the `isError` boolean.

That's backwards from how useful the two cases actually are. A
transport-level JSON-RPC error is often generic ("Method not found").
A tool error is where MCP servers put the good stuff: the tool caught
its own exception and MCP wraps it into `result.content`, normally one
or more `{"type": "text", "text": "..."}` blocks with the actual
explanation. Checked what that looks like for real rather than
assuming the shape -- called this project's own `boom()` fixture
through a live proxy and printed the raw result:

```
content=[TextContent(type='text', text='Error executing tool boom: this
tool always fails, on purpose')]
```

That text was being thrown away every single time, for every server,
since day one. Pulled it out in `_tool_error_text()`, stored as
`tool_error_message` (truncated the same way the unparsed-line path
already is, so one huge tool result can't blow up the log), and wired
it into both places someone actually looks at a failure:

- `tail` appends it to the red trace line instead of leaving it bare.
- `stats`'s printed report now lists up to 5 real failure messages
  under the count summary -- transport, tool, and proxy errors all
  pulled from the same field they already carry. This is the one that
  matters most for the CI use case: `greenlight stats || exit 1` in a
  pipeline used to tell you a run failed and made you go dig through
  the trace file to find out why. Now the reason is right there in the
  job output.

## Verification

Same discipline as every fix before this one: reproduced the exact
shape live before writing the fix (the boom() call above), not
guessed at from the MCP spec. Added coverage in two places --
`test_proxy_e2e.py` now asserts the real boom() text survives into the
stdio log, and a new `test_failure_messages` in `test_stats.py` checks
it shows up in both the `compute_stats()` dict and the printed report.
Full suite: 9/9 passing, including a fresh HTTP-proxy run confirming
the same field comes through that path too (`record()` is shared, so
one fix, not two, same as the non-dict-JSON fix).

## Status

No new external engagement since the awesome-mcp-devtools merge --
still 0 stars, 0 forks, no new issues or PRs. Not chasing that with
busywork; this fix is unrelated to distribution, it's a real gap in
what the tool actually tells you when something breaks, found by
reading the code with "would this actually help someone debugging a
real failure" as the question, not "what's left on a checklist."
