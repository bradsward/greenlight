"""
Session logs must land in one predictable place no matter where the
proxy was launched from, and a log location that can't be written must
never stop the user's real server from starting.

Both came from the same real bug: logs used to go to ./sessions relative
to the working directory. A real MCP client (Claude Desktop on macOS
commonly launches servers with cwd=/) made that unwritable, and the
proxy crashed with PermissionError before ever spawning the server.

Usage:
    .venv\\Scripts\\python.exe tests\\test_log_location.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.paths import ENV_VAR, sessions_dir  # noqa: E402

PYTHON = sys.executable
FIXTURE = str(ROOT / "tests" / "fixture_server.py")


async def _drive(params: StdioServerParameters) -> None:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("add", {"a": 2, "b": 2})
            assert not result.is_error, result


def test_resolution_order() -> None:
    saved = os.environ.pop(ENV_VAR, None)
    try:
        assert sessions_dir() == Path.home() / ".greenlight" / "sessions"
        os.environ[ENV_VAR] = "/from/env"
        assert sessions_dir() == Path("/from/env")
        assert sessions_dir("/from/flag") == Path("/from/flag")
    finally:
        os.environ.pop(ENV_VAR, None)
        if saved is not None:
            os.environ[ENV_VAR] = saved
    print("resolution order: --log-dir > $GREENLIGHT_SESSIONS_DIR > ~/.greenlight/sessions")


def test_log_dir_independent_of_cwd() -> None:
    with tempfile.TemporaryDirectory() as launch_dir, tempfile.TemporaryDirectory() as log_dir:
        params = StdioServerParameters(
            command=PYTHON,
            args=["-m", "greenlight.cli", "run", "--name", "cwd-test", "--log-dir", log_dir,
                  "--", PYTHON, FIXTURE],
            cwd=launch_dir,
        )
        asyncio.run(_drive(params))
        assert list(Path(log_dir).glob("cwd-test-*.jsonl")), "no log written to --log-dir"
        assert not (Path(launch_dir) / "sessions").exists(), "log leaked into the launch cwd"
    print("--log-dir: log written there, nothing written to the launch cwd")


def test_env_var() -> None:
    with tempfile.TemporaryDirectory() as launch_dir, tempfile.TemporaryDirectory() as log_dir:
        params = StdioServerParameters(
            command=PYTHON,
            args=["-m", "greenlight.cli", "run", "--name", "env-test", "--", PYTHON, FIXTURE],
            cwd=launch_dir,
            env={**get_default_environment(), ENV_VAR: log_dir},
        )
        asyncio.run(_drive(params))
        assert list(Path(log_dir).glob("env-test-*.jsonl")), f"no log written to ${ENV_VAR}"
    print(f"${ENV_VAR}: log written there")


def test_unwritable_log_dir_still_relays() -> None:
    # A log dir whose parent is a regular file can't be created by anyone,
    # root included, on any OS -- a portable stand-in for an unwritable
    # directory (chmod tricks don't stop root and don't exist on Windows).
    with tempfile.TemporaryDirectory() as tmp:
        blocker = Path(tmp) / "not-a-dir"
        blocker.write_text("")
        params = StdioServerParameters(
            command=PYTHON,
            args=["-m", "greenlight.cli", "run", "--log-dir", str(blocker / "sessions"),
                  "--", PYTHON, FIXTURE],
            cwd=tmp,
        )
        asyncio.run(_drive(params))
    print("unwritable log dir: server still started and answered, proxy relayed unrecorded")


if __name__ == "__main__":
    test_resolution_order()
    test_log_dir_independent_of_cwd()
    test_env_var()
    test_unwritable_log_dir_still_relays()
