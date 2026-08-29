# Greenlight - Day 7 notes

## Fixed the two open issues

Both were filed honestly (checked against real behavior before opening
them, not guessed), and both got fixed the same way: reproduce for
real, fix, verify the fix against the real case, run the full suite.

### Issue #2: unreachable target crashed the handler

urllib.request.urlopen only catches HTTPError, which is actually a
URLError subclass -- it only covers "the target responded with an
error status," not "the target never responded at all" (connection
refused, DNS failure, timeout). Added a URLError handler after the
HTTPError one. The client now gets a clean 502 with a JSON-RPC-shaped
error body instead of a dropped connection, and the failure gets
logged as a new entry type, proxy_error, distinct from both a
transport-level JSON-RPC error and a tool_error, since neither of
those apply when nothing came back at all. tail and stats both handle
it now (red in the trace, counted toward failed).

### Issue #3: SSE CRLF split across a chunk-read boundary

Refactored the buffering logic out of the handler into a standalone
function, consume_sse_buffer, specifically so the fix could be tested
without needing to force real TCP segment boundaries to split exactly
on a \r\n, which isn't practical to do reliably over a real socket.
Fix itself: re-normalize the whole accumulated buffer (previous tail
plus new chunk) every read, not just the new chunk, so a \r\n split
across two reads always ends up adjacent before the boundary check
runs.

## A bug in my own test, not the product

First version of the issue #2 test used a real HTTP request through
the proxy as a "is it up yet" readiness check. The target is
deliberately dead in this test, so every readiness attempt legitimately
failed and got logged -- 14 proxy_error entries instead of the 1 the
real test body produced, because the readiness loop was quietly
generating real traffic of its own. Fixed by checking the proxy's own
port with a raw socket connect instead of sending traffic through it.
Same category of mistake as the day 6 test bug (a before/after
snapshot assumption that didn't fit a standing-process architecture) --
different bug, same lesson: a test's own setup code can be the thing
that's wrong, not just the code under test.

## A gap closed on reasoning, not on a reproduced failure (worth being honest about the difference)

Went looking for the next real gap instead of stopping at "issues #2
and #3 are closed." The stdio proxy only ever has one caller writing to
the session log. The HTTP proxy uses ThreadingHTTPServer, so multiple
real client connections can call ProxySession.record() concurrently --
and _write() had no lock around the shared log file handle, only
self._lock protecting the _pending dict.

Fired 60 concurrent requests across 20 threads at the HTTP proxy to
check for actual corruption. Didn't find any -- 0 malformed lines. That
matters: I'm not claiming this was a reproduced bug the way #2 and #3
were. The file's opened with buffering=1 (line-buffered), so every
write triggers a real flush syscall, and Python can release the GIL
during a blocking syscall, which is exactly the kind of window a race
like this needs -- I just didn't hit it in one test run on a fast local
machine. Added the lock anyway, since it's one line, free, and closes a
real architectural gap regardless of whether today's test happened to
trigger it. Recorded as "fixed preventively," not "fixed a confirmed
bug" -- those are different claims and worth keeping distinct rather
than dressing up reasoning as a reproduction.

## Status

Both issues closed, plus the concurrency lock. Full suite (6 test files)
passes locally and in CI, both platforms, before and after the lock.
