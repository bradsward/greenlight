"""
End-to-end validation: drive a real MCP client session THROUGH greenlight
against a real MCP server, then check both that the protocol worked
normally (the proxy is transparent) and that the session log correctly
recorded what happened.

This is deliberately not a unit test with mocks -- the whole point of
Greenlight is to sit in a real MCP stdio stream without breaking it, so
the only test that actually proves that is a real session.

Usage:
    .venv\\Scripts\\python.exe tests\\test_proxy_e2e.py
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "sessions"
PYTHON = sys.executable


async def main() -> None:
    before = set(SESSIONS_DIR.glob("*.jsonl")) if SESSIONS_DIR.exists() else set()

    # This is the exact shape of command a real MCP host config would use:
    # instead of running the server directly, run it through `greenlight run`.
    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "run", "--name", "fixture-e2e", "--",
              PYTHON, str(ROOT / "tests" / "fixture_server.py")],
        cwd=str(ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("initialize: ok")

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            assert names == ["add", "boom", "slow_echo"], names
            print(f"list_tools: ok ({names})")

            add_result = await session.call_tool("add", {"a": 2, "b": 3})
            assert not add_result.is_error, add_result
            print(f"call_tool(add): ok -> {add_result.content}")

            echo_result = await session.call_tool("slow_echo", {"text": "hi", "delay_ms": 150})
            assert not echo_result.is_error, echo_result
            print(f"call_tool(slow_echo): ok -> {echo_result.content}")

            boom_result = await session.call_tool("boom", {})
            assert boom_result.is_error, "expected boom() to report as an error"
            print(f"call_tool(boom): ok, correctly reported as error")

    after = set(SESSIONS_DIR.glob("*.jsonl"))
    new_logs = after - before
    assert len(new_logs) == 1, f"expected exactly one new session log, got {new_logs}"
    log_path = new_logs.pop()
    print(f"\nsession log: {log_path}")

    entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    print(f"logged {len(entries)} entries")

    methods_seen = {e.get("method") for e in entries if e.get("method")}
    assert "tools/call" in methods_seen, methods_seen
    print(f"methods logged: {sorted(m for m in methods_seen if m)}")

    slow_calls = [e for e in entries if e.get("type") == "result" and e.get("latency_ms", 0) > 100]
    assert slow_calls, "expected at least one result with latency_ms > 100 (the slow_echo call)"
    print(f"latency tracking: ok (slow_echo measured at {slow_calls[0]['latency_ms']}ms)")

    # boom() fails at the tool level, not the transport level -- MCP nests
    # that inside a normal JSON-RPC "result" (isError: true), so it must
    # NOT show up as type == "error" (that's for transport-level failures).
    # It must show up as tool_error instead.
    transport_errors = [e for e in entries if e.get("type") == "error"]
    tool_errors = [e for e in entries if e.get("tool_error")]
    assert not transport_errors, f"expected no transport-level errors, got {transport_errors}"
    assert len(tool_errors) == 1, f"expected exactly one tool_error (from boom()), got {tool_errors}"
    print(f"tool-error detection: ok (boom() correctly flagged as tool_error, "
          f"not confused with a transport error)")

    # The tool-error result's own text explanation must survive into the
    # log too, not just the isError flag -- that's the difference between
    # "a call failed" and "a call failed, here's why" in `tail`/`stats`.
    message = tool_errors[0].get("tool_error_message", "")
    assert "this tool always fails, on purpose" in message, \
        f"expected boom()'s real error text in the log, got {message!r}"
    print(f"tool-error message captured: ok ({message!r})")

    print("\nALL CHECKS PASSED -- proxy is transparent and the log is accurate.")


if __name__ == "__main__":
    asyncio.run(main())
