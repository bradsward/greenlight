"""
End-to-end validation of the HTTP/Streamable-HTTP proxy against a real
server, same discipline as the stdio tests: a real MCP client session,
through the real proxy, against fixture_server.py running as an actual
separate network service (not the same process, not a mock).

Self-contained: spawns both the fixture server and the greenlight proxy
as real subprocesses, waits for each to actually be listening, runs the
test, and tears both down -- no manual pre-setup required.

Usage:
    .venv\\Scripts\\python.exe tests\\test_http_proxy.py
"""
import asyncio
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.paths import sessions_dir  # noqa: E402
SESSIONS_DIR = sessions_dir()
SERVER_PORT = 9001          # distinct from any port a human might have open manually
PROXY_PORT = 8809
TARGET_URL = f"http://127.0.0.1:{SERVER_PORT}/mcp"
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}/mcp"
PYTHON = sys.executable


def _wait_until_up(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5)
            return
        except urllib.error.HTTPError:
            return  # any HTTP response (even 4xx/5xx) means something's listening
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"{url} never came up within {timeout}s")


async def run_client_session() -> None:
    async with streamable_http_client(PROXY_URL) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("initialize: ok (through the HTTP proxy)")

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {"add", "slow_echo", "boom"} <= names, names
            print(f"list_tools: ok ({sorted(names)})")

            add_result = await session.call_tool("add", {"a": 10, "b": 15})
            assert not add_result.is_error, add_result
            assert add_result.content[0].text == "25"
            print(f"call_tool(add): ok -> {add_result.content}")

            echo_result = await session.call_tool("slow_echo", {"text": "http works", "delay_ms": 300})
            assert not echo_result.is_error, echo_result
            print(f"call_tool(slow_echo): ok -> {echo_result.content}")

            boom_result = await session.call_tool("boom", {})
            assert boom_result.is_error, "expected boom() to report as an error"
            print("call_tool(boom): ok, correctly reported as error")


def main() -> None:
    server_proc = subprocess.Popen(
        [PYTHON, str(ROOT / "tests" / "fixture_server.py"), "streamable-http", str(SERVER_PORT)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    proxy_proc = None
    try:
        _wait_until_up(TARGET_URL)
        print(f"fixture server up on :{SERVER_PORT}")

        # Snapshot BEFORE starting the proxy process, not before the
        # client connects -- the proxy creates its log file the instant
        # it starts (see ProxySession.__init__), well before any client
        # traffic. Snapshotting after that point compares the file
        # against itself and always finds "nothing new". Found this by
        # the test failing on its first self-contained run, not by
        # reasoning it out in advance.
        before = set(SESSIONS_DIR.glob("http-e2e-*.jsonl")) if SESSIONS_DIR.exists() else set()

        proxy_proc = subprocess.Popen(
            [PYTHON, "-m", "greenlight.cli", "run", "--http", TARGET_URL,
             "--port", str(PROXY_PORT), "--name", "http-e2e"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _wait_until_up(PROXY_URL)
        print(f"greenlight http proxy up on :{PROXY_PORT}\n")

        asyncio.run(run_client_session())

        after = set(SESSIONS_DIR.glob("http-e2e-*.jsonl"))
        new_logs = after - before
        assert new_logs, "expected a new session log from this run"
        log_path = max(new_logs, key=lambda p: p.stat().st_mtime)

        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        calls = [e for e in entries
                 if e.get("method") == "tools/call" and e.get("direction") == "server->client"]
        tool_errors = [e for e in entries if e.get("tool_error")]

        print(f"\nsession log: {log_path}")
        print(f"logged {len(entries)} entries, {len(calls)} tool call results, "
              f"{len(tool_errors)} tool_error(s) flagged")
        assert len(calls) == 3, f"expected 3 tools/call results logged, got {len(calls)}"
        assert len(tool_errors) == 1, f"expected exactly 1 tool_error (boom), got {len(tool_errors)}"

        slow = [e for e in entries if e.get("latency_ms", 0) > 250]
        assert slow, "expected the slow_echo call's latency to be captured over the HTTP proxy too"
        print(f"latency tracking over HTTP: ok ({slow[0]['latency_ms']}ms captured)")

        print("\nALL CHECKS PASSED -- HTTP proxy is transparent and the log is accurate.")
    finally:
        for proc in (proxy_proc, server_proc):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    main()
