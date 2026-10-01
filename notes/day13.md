# Greenlight - Day 13 notes

## One real bug, found by checking consistency across the codebase

Went looking for a single real thing to fix rather than another
feature. Noticed `render.py`'s `tail_file` already does this:

```python
try:
    entry = json.loads(line)
except json.JSONDecodeError:
    continue
```

Neither `stats.py`'s `compute_stats` nor the new `serve.py` tools do
the same thing -- both just `json.loads(line)` directly over every
line in the file. Same input (a session log), same realistic failure
mode (a truncated last line), handled safely in one place and not in
two others that read the identical files.

Reproduced before fixing, same as always: took a real recorded session
log, cut its last line in half with no trailing newline -- exactly
what a hard kill, an OOM kill, a crash, or power loss mid-write leaves
behind, since the writer locks around one line at a time but doesn't
control what happens if the whole process dies partway through a
syscall. Ran `greenlight stats` on it. Got an unhandled
`JSONDecodeError` traceback instead of a report.

That's a bad failure mode specifically for this tool. `stats` is
explicitly meant to be CI-safe (`greenlight stats || exit 1`), and the
one scenario most likely to produce a truncated log -- the proxied
process actually crashing -- is exactly the scenario where you most
need the report, not a stack trace in your CI output burying whatever
real information made it to disk before the crash.

Fixed both call sites the same way `tail_file` already does it: skip
the line, count it. Added it as a new `corrupted_lines` field rather
than folding it into the existing `unparsed_lines` count, since those
mean different things -- `unparsed_lines` is a line that's valid JSON
but wasn't a usable JSON-RPC message; `corrupted_lines` is a line that
isn't valid JSON at all, a different and lower-level failure. A
corrupted line also now fails the `stats` pass/fail check -- the
process that was writing it almost certainly didn't exit cleanly,
which is itself a real thing to flag, not something to quietly paper
over.

## Verification

New test (`test_corrupted_log_line.py`) builds a log with two valid
entries and one truncated one, checks `compute_stats` returns the two
real entries correctly, reports `corrupted_lines == 1`, and marks the
session failed -- plus a second check that a normal clean log reports
zero corrupted lines, so the fix doesn't introduce a false failure on
anything that was already working.

13/13 test files passing.

## Status

Still 0 stars, 0 forks, no new issues or PRs. Spent today on this
instead of outreach on purpose -- a tool whose whole pitch is "trust
this when something breaks" shouldn't itself fall over on the exact
kind of mess a real crash leaves behind.
