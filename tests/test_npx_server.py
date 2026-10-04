"""
Validates greenlight against a real, third-party, npx-launched MCP
server -- the official reference server, not something hand-picked to be
easy. This is the realistic case: most local MCP servers are started via
`npx`, and on Windows that specifically exercises the PATHEXT resolution
fix in cli.py (`npx` is actually `npx.cmd`), which the fixture-server
tests never touched because they invoke `python` directly.

Usage:
    .venv\\Scripts\\python.exe tests\\test_npx_server.py
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from greenlight.paths import sessions_dir  # noqa: E402
SESSIONS_DIR = sessions_dir()
PYTHON = sys.executable


async def main() -> None:
    before = set(SESSIONS_DIR.glob("*.jsonl")) if SESSIONS_DIR.exists() else set()

    # The real-world shape: greenlight wraps `npx`, not a python script.
    # cli.py's shutil.which() resolution is what makes this work at all
    # on Windows -- subprocess.Popen(["npx", ...]) with shell=False fails
    # outright otherwise, because Windows doesn't apply PATHEXT the way a
    # real shell does.
    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "run", "--name", "npx-everything", "--",
              "npx", "-y", "@modelcontextprotocol/server-everything", "stdio"],
        cwd=str(ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("initialize: ok (through greenlight, wrapping a real npx server)")

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "echo" in names and "get-sum" in names, names
            print(f"list_tools: ok ({len(names)} tools)")

            echo_result = await session.call_tool("echo", {"message": "hello from greenlight"})
            assert not echo_result.is_error, echo_result
            print(f"call_tool(echo): ok -> {echo_result.content}")

            sum_result = await session.call_tool("get-sum", {"a": 4, "b": 5})
            assert not sum_result.is_error, sum_result
            print(f"call_tool(get-sum): ok -> {sum_result.content}")

    after = set(SESSIONS_DIR.glob("*.jsonl"))
    new_logs = after - before
    assert len(new_logs) == 1, f"expected exactly one new session log, got {new_logs}"
    log_path = new_logs.pop()

    entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    calls = [e for e in entries if e.get("method") == "tools/call" and e.get("direction") == "server->client"]
    assert len(calls) == 2, f"expected 2 tools/call results logged, got {len(calls)}"
    print(f"\nsession log: {log_path}")
    print(f"logged {len(entries)} entries, {len(calls)} tool call results, "
          f"none malformed/unparsed: {all(e.get('parsed', True) for e in entries)}")

    print("\nALL CHECKS PASSED -- greenlight works against a real npx-launched "
          "MCP server on Windows, not just the Python fixture.")


if __name__ == "__main__":
    asyncio.run(main())
