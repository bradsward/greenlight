"""
Verifies tail_file(follow=True) actually picks up new lines as they're
written, not just replays what already existed when it started. Runs
the real proxy against the real fixture server, starts following the log
partway through the session, and checks that later calls show up.
"""
import asyncio
import sys
import threading
import time
from io import StringIO
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from rich.console import Console

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.render import tail_file  # noqa: E402
import greenlight.render as render_module  # noqa: E402
from greenlight.paths import sessions_dir  # noqa: E402

PYTHON = sys.executable


async def main() -> None:
    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "run", "--name", "follow-test", "--",
              PYTHON, str(ROOT / "tests" / "fixture_server.py")],
        cwd=str(ROOT),
    )

    captured = StringIO()
    render_module.console = Console(file=captured, force_terminal=False)

    follow_thread = None
    log_path_holder: dict = {}

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("add", {"a": 1, "b": 1})

            sessions = sessions_dir()
            candidates = sorted(sessions.glob("follow-test-*.jsonl"), key=lambda p: p.stat().st_mtime)
            log_path = candidates[-1]
            log_path_holder["path"] = log_path
            print(f"following {log_path} while the session is still open")

            follow_thread = threading.Thread(target=tail_file, args=(log_path,), kwargs={"follow": True}, daemon=True)
            follow_thread.start()
            time.sleep(0.3)

            before = captured.getvalue()
            assert "add" not in before or before.count("tools/call") >= 1, "sanity check on initial capture"

            # this call happens AFTER tail_file(follow=True) is already running
            await session.call_tool("slow_echo", {"text": "live", "delay_ms": 50})
            time.sleep(0.5)

    output = captured.getvalue()
    call_count = output.count("tools/call")
    print(f"\ncaptured {call_count} tools/call lines while following live")
    assert call_count >= 4, (
        f"expected at least 4 tools/call lines (2 calls x request+response) "
        f"captured DURING live follow, got {call_count}\n---\n{output}"
    )
    print("PASS: tail -f picks up new messages as they're written, not just at startup")


if __name__ == "__main__":
    asyncio.run(main())
