"""
Re-records the two session logs the README demo is built from, by driving
real MCP traffic through the real proxy (nothing is hand-edited):

  demo-session.jsonl  tests/fixture_server.py, via a real MCP client:
                      a quick call, a slow call, and a tool that raises.
  bad-session.jsonl   tests/bad_fixture_server.py, a server built to make
                      the mistakes `greenlight check` looks for.

Needs the dev extras (the `mcp` SDK) installed.

Usage:
    .venv\\Scripts\\python.exe examples\\record_demo_sessions.py
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _only_log(log_dir: str) -> Path:
    (log,) = Path(log_dir).glob("*.jsonl")
    return log


async def record_demo(log_dir: str) -> None:
    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "run", "--name", "demo", "--log-dir", log_dir, "--",
              PYTHON, str(ROOT / "tests" / "fixture_server.py")],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.list_tools()
            await session.call_tool("add", {"a": 2, "b": 3})
            await session.call_tool("slow_echo", {"text": "hello", "delay_ms": 650})
            await session.call_tool("boom", {})


def record_bad(log_dir: str) -> None:
    def msg(msg_id, method, params=None):
        m = {"jsonrpc": "2.0", "method": method}
        if msg_id is not None:
            m["id"] = msg_id
        if params is not None:
            m["params"] = params
        return json.dumps(m) + "\n"

    client = (
        msg(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "demo", "version": "0"}})
        + msg(None, "notifications/initialized")
        + msg(2, "tools/list")
        + msg(3, "tools/call", {"name": "ok_tool", "arguments": {}})
    )
    subprocess.run(
        [PYTHON, "-m", "greenlight.cli", "run", "--name", "bad", "--log-dir", log_dir, "--",
         PYTHON, str(ROOT / "tests" / "bad_fixture_server.py")],
        input=client, capture_output=True, text=True, timeout=60, check=True, cwd=ROOT,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as demo_dir, tempfile.TemporaryDirectory() as bad_dir:
        asyncio.run(record_demo(demo_dir))
        record_bad(bad_dir)
        shutil.copy(_only_log(demo_dir), ROOT / "examples" / "demo-session.jsonl")
        shutil.copy(_only_log(bad_dir), ROOT / "examples" / "bad-session.jsonl")
    print("wrote examples/demo-session.jsonl and examples/bad-session.jsonl")


if __name__ == "__main__":
    main()
