"""
greenlight stats is meant to be usable as a CI check -- its exit code has
to be trustworthy, not just its printed output. Tests both directions
against real recorded sessions: one with a known failure
(examples/demo-session.jsonl), one clean.

Usage:
    .venv\\Scripts\\python.exe tests\\test_stats.py
"""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.cli import main as cli_main  # noqa: E402
from greenlight.stats import compute_stats, format_stats  # noqa: E402

PYTHON = sys.executable


def test_known_failure() -> None:
    path = ROOT / "examples" / "demo-session.jsonl"
    stats = compute_stats(path)
    assert stats["failed"] is True
    assert stats["tool_errors"] == 1
    assert stats["transport_errors"] == 0

    exit_code = cli_main(["stats", str(path)])
    assert exit_code == 1, f"expected exit 1 on a session with a known failure, got {exit_code}"
    print("known-failure session: stats correctly reports failed=True, exit code 1")


async def _record_clean_session() -> Path:
    sessions_dir = ROOT / "sessions"
    before = set(sessions_dir.glob("clean-*.jsonl")) if sessions_dir.exists() else set()

    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "run", "--name", "clean", "--",
              PYTHON, str(ROOT / "tests" / "fixture_server.py")],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("add", {"a": 1, "b": 1})
            assert not result.is_error

    after = set(sessions_dir.glob("clean-*.jsonl"))
    new_logs = after - before
    assert len(new_logs) == 1
    return new_logs.pop()


def test_clean_session() -> None:
    path = asyncio.run(_record_clean_session())
    stats = compute_stats(path)
    assert stats["failed"] is False, stats
    assert stats["tool_errors"] == 0
    assert stats["transport_errors"] == 0

    exit_code = cli_main(["stats", str(path)])
    assert exit_code == 0, f"expected exit 0 on a clean session, got {exit_code}"
    print("clean session: stats correctly reports failed=False, exit code 0")


async def _record_boom_session() -> Path:
    sessions_dir = ROOT / "sessions"
    before = set(sessions_dir.glob("boom-*.jsonl")) if sessions_dir.exists() else set()

    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "run", "--name", "boom", "--",
              PYTHON, str(ROOT / "tests" / "fixture_server.py")],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("boom", {})
            assert result.is_error

    after = set(sessions_dir.glob("boom-*.jsonl"))
    new_logs = after - before
    assert len(new_logs) == 1
    return new_logs.pop()


def test_failure_messages() -> None:
    # stats shouldn't just count failures -- a CI log with "1 tool error(s)"
    # and nothing else forces you to go dig through the trace to find out
    # what actually broke. The real message MCP gave for the failure has to
    # make it all the way through to both the dict and the printed report.
    path = asyncio.run(_record_boom_session())
    stats = compute_stats(path)
    assert stats["tool_errors"] == 1
    assert len(stats["failure_messages"]) == 1
    assert "this tool always fails, on purpose" in stats["failure_messages"][0]

    report = format_stats(stats, path)
    assert "this tool always fails, on purpose" in report
    print(f"failure messages: ok (surfaced in both stats dict and printed report)")


if __name__ == "__main__":
    test_known_failure()
    test_clean_session()
    test_failure_messages()
    print("\nALL CHECKS PASSED -- stats exit code is trustworthy in both directions.")
