"""
greenlight serve exposes this project's own session data as an MCP
server. Tested the same way the rest of this project tests MCP behavior:
spawn the real thing as a subprocess and drive it with a real MCP client,
not a mock.

Uses a hand-crafted session log with known entries (rather than whatever
happens to be the "most recent" session from other tests) so the
assertions aren't order-dependent on what else has run before this file.

Usage:
    .venv\\Scripts\\python.exe tests\\test_serve.py
"""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "sessions"
PYTHON = sys.executable


def _write_fixture_session() -> str:
    """A hand-crafted session log with one clean result, one tool error,
    and one transport error -- known values, so get_failures/get_trace
    can be asserted against exactly, not just "some plausible-looking
    data"."""
    name = f"serve-test-{uuid.uuid4().hex[:8]}.jsonl"
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / name

    now = time.time()
    entries = [
        {"ts": now, "direction": "client->server", "parsed": True,
         "type": "request", "method": "tools/call"},
        {"ts": now + 0.01, "direction": "server->client", "parsed": True,
         "type": "result", "method": "tools/call", "latency_ms": 5.0},
        {"ts": now + 0.02, "direction": "client->server", "parsed": True,
         "type": "request", "method": "tools/call"},
        {"ts": now + 0.03, "direction": "server->client", "parsed": True,
         "type": "result", "method": "tools/call", "latency_ms": 3.0,
         "tool_error": True, "tool_error_message": "the fixture's own known failure text"},
        {"ts": now + 0.04, "direction": "server->client", "parsed": True,
         "type": "error", "error": {"message": "the fixture's own known transport failure"}},
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return name


async def main() -> None:
    session_name = _write_fixture_session()

    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "serve"],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("initialize: ok")

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            assert names == ["get_failures", "get_session_stats", "get_trace", "list_sessions"], names
            print(f"list_tools: ok ({names})")

            r = await session.call_tool("list_sessions", {})
            listed = [json.loads(block.text) for block in r.content]
            assert any(s["name"] == session_name for s in listed), listed
            print("list_sessions: ok (fixture session present)")

            r = await session.call_tool("get_session_stats", {"session": session_name})
            stats = json.loads(r.content[0].text)
            assert stats["tool_errors"] == 1, stats
            assert stats["transport_errors"] == 1, stats
            assert stats["failed"] is True, stats
            assert "the fixture's own known failure text" in stats["failure_messages"]
            assert "the fixture's own known transport failure" in stats["failure_messages"]
            print("get_session_stats: ok (matches the fixture exactly)")

            r = await session.call_tool("get_failures", {"session": session_name, "limit": 10})
            failures = [json.loads(block.text) for block in r.content]
            assert len(failures) == 2, failures
            kinds = {f["kind"] for f in failures}
            assert kinds == {"tool_error", "transport_error"}, kinds
            messages = {f["message"] for f in failures}
            assert "the fixture's own known failure text" in messages
            assert "the fixture's own known transport failure" in messages
            print("get_failures: ok (both real failures, with their real messages)")

            r = await session.call_tool("get_trace", {"session": session_name, "limit": 10})
            trace_lines = [block.text for block in r.content]
            assert len(trace_lines) == 5, trace_lines
            assert any("FAILED (tool error): the fixture's own known failure text" in line
                       for line in trace_lines), trace_lines
            assert any("FAILED: the fixture's own known transport failure" in line
                       for line in trace_lines), trace_lines
            print("get_trace: ok (same formatting `tail` uses, as plain text)")

            # Not asserting the exact wording here: the installed mcp SDK
            # wraps a raised exception's message differently across
            # versions (see test_tool_error_extraction.py and
            # test_proxy_e2e.py for the same lesson learned earlier) --
            # one SDK version appends _resolve_session's own message text,
            # another truncates to just "Error executing tool X". Both are
            # fine; what actually matters is that this comes back as a
            # proper tool-level error, not a crash or a silent wrong answer.
            r = await session.call_tool("get_session_stats", {"session": "no-such-session.jsonl"})
            assert r.is_error, "expected an error for a session that doesn't exist"
            assert "get_session_stats" in r.content[0].text
            print("unknown session: ok (reported as a tool error, not a crash)")

    print("\nALL CHECKS PASSED -- greenlight serve exposes real session data correctly over MCP.")


if __name__ == "__main__":
    asyncio.run(main())
