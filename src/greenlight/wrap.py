"""
Read-only helper for pointing an existing MCP client config at Greenlight.

Finds known MCP client config files (Claude Desktop, Claude Code's
project-local .mcp.json) and, for each server entry, prints exactly what
it would look like rewritten to run through `greenlight run` -- nothing
here ever writes to disk. Copying a suggestion in is a manual, deliberate
step, same as editing the config by hand, just without having to work out
the wrapping syntax (and the exact command path to use so Claude Desktop
can actually find it -- see the sys.executable choice below) yourself.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

# A marker used to detect an entry this tool (or a previous run of it)
# already rewrote, so re-running `wrap` on an already-wrapped config
# doesn't suggest wrapping it a second time.
_GREENLIGHT_MARKER = "greenlight.cli"


def known_config_locations() -> list[Path]:
    """Well-known MCP client config file locations, OS-appropriate. Not
    every path returned here necessarily exists -- callers filter with
    find_configs()."""
    locations: list[Path] = []

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            locations.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    elif sys.platform == "darwin":
        locations.append(
            Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        )
    else:
        # No official Claude Desktop release for Linux -- some community
        # setups use this path anyway, only surfaced if it's actually there.
        locations.append(Path.home() / ".config" / "Claude" / "claude_desktop_config.json")

    return locations


def find_configs(cwd: Optional[Path] = None, known: Optional[list[Path]] = None) -> list[Path]:
    """Every known config location that actually exists on disk, plus a
    project-local .mcp.json (Claude Code's project-scoped server config --
    same {"mcpServers": {...}} shape) if this directory has one.

    `known` overrides the OS-detected locations (known_config_locations())
    -- mainly so tests can run in isolation from whatever's actually
    installed on the machine running them."""
    cwd = cwd or Path.cwd()
    candidates = (known if known is not None else known_config_locations()) + [cwd / ".mcp.json"]

    found: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            found.append(path)
    return found


def load_servers(path: Path) -> dict:
    """Parse a client config and return its mcpServers dict. Raises
    ValueError with a clear message on anything unreadable -- this only
    ever reads, so a bad file should be reported plainly, not guessed at
    or partially handled."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError(f'{path} has no "mcpServers" object')
    return servers


def is_already_wrapped(entry: dict) -> bool:
    args = entry.get("args") or []
    return any(_GREENLIGHT_MARKER in str(a) for a in args)


def wrapped_entry(name: str, entry: dict) -> Optional[dict]:
    """Given one server's existing config entry, return it rewritten to run
    through `greenlight run`, or None if this entry isn't something wrap()
    knows how to rewrite: already wrapped, or not a stdio command (a
    url-based entry needs the --http reverse-proxy flow instead of a
    command rewrite, which is a different enough shape of change that this
    only points at how, rather than guessing at it)."""
    if "command" not in entry or is_already_wrapped(entry):
        return None

    original_command = entry["command"]
    original_args = entry.get("args", [])

    wrapped = dict(entry)
    # sys.executable, not a bare "greenlight" -- Claude Desktop on macOS is
    # launched outside a login shell and often can't see the PATH a
    # terminal would, a well-known way MCP server commands silently fail
    # to start. An absolute interpreter path sidesteps that regardless of
    # what environment ends up spawning this.
    wrapped["command"] = sys.executable
    wrapped["args"] = [
        "-m", "greenlight.cli", "run", "--name", name, "--",
        original_command, *original_args,
    ]
    return wrapped


def _indent(text: str, spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())


def format_suggestions(path: Path, servers: dict) -> str:
    """Human-readable, copy-pasteable suggestion block for every server in
    this config wrap() knows how to rewrite. Doesn't touch the file."""
    lines = [str(path)]
    any_suggested = False

    for name, entry in sorted(servers.items()):
        if is_already_wrapped(entry):
            lines.append(f"\n  {name}: already wrapped, skipping")
            continue

        wrapped = wrapped_entry(name, entry)
        if wrapped is None:
            lines.append(
                f"\n  {name}: no \"command\" field (likely a remote/URL server) -- "
                f"use `greenlight run --http <url>` for that one instead"
            )
            continue

        any_suggested = True
        lines.append(f"\n  {name}: replace this server's entry with:")
        lines.append(_indent(json.dumps(wrapped, indent=2)))

    if not any_suggested:
        lines.append("\n  nothing to wrap here")

    return "\n".join(lines)
