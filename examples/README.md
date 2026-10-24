# examples/

What the README demo is built from.

- `demo-session.jsonl`: a session recorded through the real proxy
  against `tests/fixture_server.py`, driven by a real MCP client: a quick
  call, a slow call, and a tool that raises.
- `bad-session.jsonl`: a session recorded through the real proxy against
  `tests/bad_fixture_server.py`, a server built to make the mistakes
  `greenlight check` looks for.
- `record_demo_sessions.py`: re-records both of the above (needs the dev
  extras).
- `make_demo_gif.py`: builds `demo.gif`. It captures what `greenlight tail`
  and `greenlight check` print, with colors, by calling the same functions
  the CLI calls, and first asserts that the text is identical to what the
  real CLI prints. Only the rendering is a stand-in for a screen
  recording (Pillow draws the frames; it isn't a dependency of
  greenlight, just needed to rebuild the GIF).
- `demo.tape`: a `vhs` script that would record a real terminal instead.
  It didn't work in the environment this was built in (see `notes/day4.md`
  for why: a headless-browser hang, not a bug in the script). Kept as a
  legitimate alternative where it does work.

Rebuild:

```bash
.venv\Scripts\python.exe examples\record_demo_sessions.py   # only if the fixtures should change
.venv\Scripts\python.exe examples\make_demo_gif.py
```
