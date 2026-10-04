"""
greenlight serve -- exposes this project's own session/trace data as an
MCP server, so an agentic MCP client (Claude Code, Cursor, or anything
else that can add an MCP server to its own config) can query real trace
data directly instead of a human relaying `tail`/`stats` terminal output
back into a conversation by hand.

Optional dependency: needs `mcp`, which the base install doesn't pull in
(pip install greenlight-mcp[serve]) -- most users only ever need
run/tail/stats, and the base install stays deliberately minimal for them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer

from greenlight.check import check_session
from greenlight.render import _format_entry, latest_session
from greenlight.stats import compute_stats


def _resolve_session(session: Optional[str], sessions: Path) -> Path:
    """A session argument can be a bare filename (resolved under the
    sessions directory), a full/relative path, or omitted entirely (the most
    recent session). Raising a plain exception here, rather than
    swallowing the problem, is deliberate -- the mcp SDK turns a raised
    exception into a proper tool-level isError result with the message
    intact, exactly the mechanism this project's own record() extracts
    and surfaces (see proxy.py's _tool_error_text)."""
    if session is None:
        path = latest_session(sessions)
        if path is None:
            raise FileNotFoundError(f"no session logs found in {sessions}")
        return path

    path = Path(session)
    if not path.is_absolute():
        candidate = sessions / session
        if candidate.exists():
            return candidate
    if not path.exists():
        raise FileNotFoundError(f"no such session log: {session}")
    return path


def _read_entries(path: Path) -> list[dict]:
    # Same reasoning as stats.py's compute_stats: a session log's last
    # line can be truncated if the process writing it didn't exit
    # cleanly, and a raised JSONDecodeError here would turn that into a
    # tool-level crash instead of just quietly skipping the one line that
    # didn't make it to disk intact.
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def build_server(sessions: Path) -> MCPServer:
    server = MCPServer("greenlight")

    @server.tool()
    def list_sessions() -> list[dict]:
        """List recorded Greenlight session logs, most recently modified first."""
        if not sessions.exists():
            return []
        files = sorted(sessions.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {
                "name": p.name,
                "path": str(p),
                "modified_ts": p.stat().st_mtime,
                "size_bytes": p.stat().st_size,
            }
            for p in files
        ]

    @server.tool()
    def get_session_stats(session: Optional[str] = None) -> dict:
        """Message counts, latency (min/median/max, by method), and a pass/fail verdict for
        a recorded session. Defaults to the most recent session if none is given."""
        return compute_stats(_resolve_session(session, sessions))

    @server.tool()
    def get_failures(session: Optional[str] = None, limit: int = 10) -> list[dict]:
        """The actual failures from a session, most recent first -- transport-level JSON-RPC
        errors, tool-level failures (with the real error message the tool itself gave, not
        just a flag), and proxy errors (target unreachable). This is the direct answer to
        "what broke and why", without having to read the raw trace."""
        entries = _read_entries(_resolve_session(session, sessions))
        failures = []
        for e in entries:
            if e.get("type") == "error":
                failures.append({
                    "ts": e["ts"], "method": e.get("method"), "kind": "transport_error",
                    "message": e.get("error", {}).get("message"),
                })
            elif e.get("tool_error"):
                failures.append({
                    "ts": e["ts"], "method": e.get("method"), "kind": "tool_error",
                    "message": e.get("tool_error_message"),
                })
            elif e.get("type") == "proxy_error":
                failures.append({
                    "ts": e["ts"], "method": e.get("method"), "kind": "proxy_error",
                    "message": e.get("error", {}).get("message"),
                })
        failures.sort(key=lambda f: f["ts"], reverse=True)
        return failures[:limit]

    @server.tool()
    def get_problems(session: Optional[str] = None) -> list[dict]:
        """Protocol and server bugs in a session that don't show up as failed calls: the server
        printing to stdout, invalid or unportable tool definitions, requests that never got a
        response, very slow calls. Same findings as `greenlight check`."""
        return [vars(f) for f in check_session(_resolve_session(session, sessions))]

    @server.tool()
    def get_trace(session: Optional[str] = None, limit: int = 50) -> list[str]:
        """The last N formatted trace lines from a session -- the same text `greenlight tail`
        prints, plain text (no color codes). Defaults to the most recent session."""
        entries = _read_entries(_resolve_session(session, sessions))
        lines = [_format_entry(e)[0] for e in entries]
        return lines[-limit:]

    return server


def run_serve(sessions: Path) -> int:
    build_server(sessions).run()
    return 0
