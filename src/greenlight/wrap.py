"""
Read-only helper for pointing an existing MCP client config at Greenlight.

Finds known MCP client config files (Claude Desktop, Claude Code's
project-local .mcp.json, Cursor, Windsurf -- all of which happen to share
the same {"mcpServers": {...}} shape) and, for each server entry, prints
exactly what it would look like rewritten to run through `greenlight run`
-- nothing here ever writes to disk. Copying a suggestion in is a manual,
deliberate step, same as editing the config by hand, just without having
to work out the wrapping syntax (and the exact command path to use so a
GUI-launched client can actually find it -- see the sys.executable choice
below) yourself.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

# A marker used to detect an entry this tool (or a previous run of it)
# already rewrote, so re-running `wrap` on an already-wrapped config
# doesn't suggest wrapping it a second time.
_GREENLIGHT_MARKER = "greenlight.cli"


def known_config_locations() -> list[Path]:
    """Well-known, machine-global MCP client config file locations. Not
    every path returned here necessarily exists -- callers filter with
    find_configs(). Project-local configs (Claude Code's .mcp.json,
    Cursor's project-level .cursor/mcp.json) are handled separately in
    find_configs(), since they're relative to a working directory rather
    than fixed per machine."""
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

    # Cursor and Windsurf both keep their global MCP config at a fixed
    # path under the home directory on every OS (unlike Claude Desktop,
    # which uses each platform's app-data convention).
    locations.append(Path.home() / ".cursor" / "mcp.json")
    locations.append(Path.home() / ".codeium" / "windsurf" / "mcp_config.json")

    return locations


def find_configs(cwd: Optional[Path] = None, known: Optional[list[Path]] = None) -> list[Path]:
    """Every known config location that actually exists on disk, plus
    project-local configs relative to `cwd` -- Claude Code's .mcp.json and
    Cursor's .cursor/mcp.json, both of which take precedence over the
    global config for the same client when a project defines its own.
    All of these happen to share the same {"mcpServers": {...}} shape.

    `known` overrides the OS-detected locations (known_config_locations())
    -- mainly so tests can run in isolation from whatever's actually
    installed on the machine running them."""
    cwd = cwd or Path.cwd()
    project_local = [cwd / ".mcp.json", cwd / ".cursor" / "mcp.json"]
    candidates = (known if known is not None else known_config_locations()) + project_local

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
    # `spawn npx ENOENT` / "Server disconnected" is the failure MCP users
    # hit most: the client launches servers with a smaller PATH than a
    # terminal has. This runs in a terminal, where the command resolves, so
    # write the full path into the config instead of a bare name.
    original_command = shutil.which(original_command) or original_command

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


_SCRIPT_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".jar", ".exe", ".bat", ".cmd")


def entry_notes(entry: dict) -> list[str]:
    """Things worth knowing before pasting a wrapped entry in: a command
    that isn't on PATH here either, and relative paths that a client
    launching from its own working directory (often `/`) won't resolve."""
    notes = []
    command = entry.get("command")
    if isinstance(command, str):
        resolved = shutil.which(command)
        if resolved is None:
            notes.append(
                f"{command!r} isn't on PATH in this terminal either, so a client won't find it "
                f"-- install it, or put the full path in the config"
            )
        elif resolved != command:
            notes.append(f"{command!r} written as {resolved!r}: clients often launch servers with "
                         f"a smaller PATH than a terminal has")
    for arg in entry.get("args") or []:
        if not isinstance(arg, str) or arg.startswith("-") or os.path.isabs(arg):
            continue
        looks_like_path = "/" in arg or "\\" in arg or arg.lower().endswith(_SCRIPT_SUFFIXES)
        if looks_like_path and Path(arg).exists():
            notes.append(
                f"argument {arg!r} is a relative path -- clients start servers from their own "
                f"working directory (often `/`), so it may not resolve; use an absolute path"
            )
    return notes


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
        # Show only the two fields that change. A server entry's `env` is
        # where API keys live, and the suggestion ends up in terminal
        # scrollback and in whatever the user pastes it into.
        lines.append(f"\n  {name}: replace this server's \"command\" and \"args\" with:")
        lines.append(_indent(json.dumps({k: wrapped[k] for k in ("command", "args")}, indent=2)))
        kept = sorted(k for k in entry if k not in ("command", "args"))
        if kept:
            lines.append(f"    (leave the rest of the entry as it is: {', '.join(kept)})")
        for note in entry_notes(entry):
            lines.append(f"    note: {note}")

    if not any_suggested:
        lines.append("\n  nothing to wrap here")

    return "\n".join(lines)
