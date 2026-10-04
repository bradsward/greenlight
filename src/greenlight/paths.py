"""
Where session logs live.

Originally this was `./sessions` relative to the current directory. That
works from a terminal, but a real MCP client (Claude Desktop, Cursor...)
launches the server command with whatever working directory it likes --
on macOS Claude Desktop commonly uses `/`, which isn't writable, so the
proxy crashed with PermissionError before the user's server ever
started. And even when the directory was writable, the logs landed
somewhere `greenlight tail` in a terminal would never look. A fixed
per-user default fixes both: every command reads and writes the same
place regardless of who launched it or from where.

Resolution order: an explicit --log-dir, then $GREENLIGHT_SESSIONS_DIR,
then ~/.greenlight/sessions.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ENV_VAR = "GREENLIGHT_SESSIONS_DIR"


def sessions_dir(override: Optional[str] = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".greenlight" / "sessions"
