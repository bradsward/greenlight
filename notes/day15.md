# Greenlight - Day 15 notes

## A transparent proxy that wasn't, for big messages

Ran greenlight against three more official reference servers (memory,
sequential-thinking, filesystem) to see whether `check` or `stats`
misreported anything on real traffic. They didn't: the only finding was
the legitimate cold-`npx` slow-start. While reading the relay code for
that, one line stood out: the child is spawned with `bufsize=0`, which
makes its stdout a raw unbuffered pipe, and `readline()` on a raw stream
reads one byte per syscall.

Timed it instead of assuming. One 4 MB JSON-RPC line: 0.08s direct,
2.26s through greenlight. Bytes identical, so nothing was ever
*wrong*, just slow, and the cost scales with size (about half a second
per MB here). Base64 screenshots and large file reads are routine MCP
traffic, so this was a real tax on exactly the messages people care
about, and it also made the latencies greenlight itself logs look worse
than the server was.

The `bufsize=0` comment said latency mattered. It does, and a buffered
reader doesn't hurt it: `readline()` on a `BufferedReader` still returns
as soon as a newline arrives, it just doesn't make one syscall per byte
to find it. Wrapped the server's stdout in one. After: 4 MB in 0.29s
(most of that is starting two interpreters), 16 MB costs about 0.2s
more than running the server directly.

## The test

The obvious test is "big message must be fast", which is exactly the
kind of timing assertion that flakes on a slow CI runner. Made it a
difference instead: time a tiny message and an 8 MB one through the
same proxy and assert the gap, so interpreter startup cancels out. Also
checked that it can fail: against the old code the gap is 4.0s, against
the limit of 1.5s; with the fix it's 0.08s. Also asserts the relayed
bytes equal what the server wrote and that the big response was still
parsed and logged.

## Status

Still no outside engagement: 0 stars, no new issues. PyPI is at its
usual handful a day. 0.5.1 is a speed fix with no behaviour change, so
it isn't urgent, but anything moving real screenshots through it will
notice.
