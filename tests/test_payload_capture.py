"""
--capture-payloads, end to end through the real proxy and a real MCP
client.

The point of the feature: when a tool call fails you can see what the
client actually sent. The point of the default: a log of metadata only is
safe to leave running, so nothing about content may be recorded unless it's
asked for. And whatever is recorded has secrets redacted *before* it's
written, which is checked on the raw file, not just on parsed fields.

Usage:
    .venv\\Scripts\\python.exe tests\\test_payload_capture.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
SECRET = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv"
PAYLOAD_KEYS = {"payload", "request_payload", "payload_truncated"}


async def drive(log_dir: str, name: str, extra_args: list[str]) -> Path:
    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "greenlight.cli", "run", "--name", name, "--log-dir", log_dir, *extra_args, "--",
              PYTHON, str(ROOT / "tests" / "fixture_server.py")],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.list_tools()
            await session.call_tool("add", {"a": 2, "b": 3})
            await session.call_tool("slow_echo", {"text": f"my key is {SECRET} ok", "delay_ms": 10})
            await session.call_tool("boom", {})
    (log,) = Path(log_dir).glob(f"{name}-*.jsonl")
    return log


def entries_of(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_cli(*args: str) -> str:
    env = dict(os.environ, NO_COLOR="1", COLUMNS="200", PYTHONIOENCODING="utf-8")
    return subprocess.run([PYTHON, "-m", "greenlight.cli", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60).stdout


def test_default_records_no_content() -> None:
    with tempfile.TemporaryDirectory() as d:
        log = asyncio.run(drive(d, "off", []))
        text = log.read_text(encoding="utf-8")
        leaked = [e for e in entries_of(log) if PAYLOAD_KEYS & e.keys()]
        assert not leaked, f"content recorded without --capture-payloads: {leaked[:1]}"
        assert SECRET not in text
    print("default: ok (no request/response content recorded, no flags needed to stay private)")


def test_capture_shows_what_was_sent_and_redacts_secrets() -> None:
    with tempfile.TemporaryDirectory() as d:
        log = asyncio.run(drive(d, "on", ["--capture-payloads"]))
        raw = log.read_text(encoding="utf-8")
        entries = entries_of(log)

        assert SECRET not in raw, "a secret passed as a tool argument reached the log file"
        assert "[redacted]" in raw and "my key is" in raw, "surrounding text should survive"

        add_req = next(e for e in entries if e.get("type") == "request" and '"name":"add"' in e.get("payload", ""))
        assert '"a":2' in add_req["payload"] and '"b":3' in add_req["payload"], add_req["payload"]

        boom = next(e for e in entries if e.get("tool_error"))
        assert '"name":"boom"' in boom["request_payload"], boom
        assert "boom" in boom["payload"], boom["payload"]   # not asserting exact SDK wording
        print("capture: ok (request params, matching arguments on the failed result, secret redacted)")

        plain = run_cli("tail", str(log))
        shown = run_cli("tail", "--payloads", str(log))
        assert "args:" not in plain and "params:" not in plain, "tail must not print content unless asked"
        assert "args:" in shown and '"name":"boom"' in shown, shown
        assert SECRET not in shown
        # every payload is ONE line, cut at the terminal edge, never wrapped onto a second one
        wide = [l for l in shown.splitlines() if l.lstrip().startswith(("params:", "result:", "args:"))]
        assert wide and all(len(l) <= 200 for l in wide), wide
        continuation = [l for l in shown.splitlines() if l and not l.startswith((" ", "\t"))
                        and not l[:2].isdigit() and not l.startswith(("watching", "->", ".", "|", "'"))
                        and "greenlight" not in l]
        assert not continuation, f"a payload wrapped onto another line: {continuation}"
        print("tail --payloads: ok (the failed call's arguments are shown only when asked for)")

        asyncio.run(check_serve(d, log.name))


async def check_serve(log_dir: str, session_name: str) -> None:
    params = StdioServerParameters(
        command=PYTHON, args=["-m", "greenlight.cli", "serve", "--log-dir", log_dir], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            without = await session.call_tool("get_failures", {"session": session_name})
            with_p = await session.call_tool("get_failures", {"session": session_name, "include_payloads": True})
            plain = [json.loads(b.text) for b in without.content]
            rich = [json.loads(b.text) for b in with_p.content]
            assert plain and not any("arguments" in f or "result" in f for f in plain), plain
            assert any('"name":"boom"' in f.get("arguments", "") for f in rich), rich
    print("serve: ok (an agent gets payloads only if it asks for them)")


def test_payload_limit_truncates() -> None:
    with tempfile.TemporaryDirectory() as d:
        log = asyncio.run(drive(d, "short", ["--capture-payloads", "--payload-limit", "60"]))
        cut = [e for e in entries_of(log) if e.get("payload_truncated")]
        assert cut, "tools/list is far longer than 60 characters; something should be marked truncated"
        assert all(len(e["payload"]) <= 60 for e in cut)
        assert "..." in run_cli("tail", "--payloads", str(log))
    print("payload limit: ok (cut at the limit, marked truncated, shown with ... in tail)")


if __name__ == "__main__":
    test_default_records_no_content()
    test_capture_shows_what_was_sent_and_redacts_secrets()
    test_payload_limit_truncates()
    print("\nALL CHECKS PASSED -- content is recorded only on request, and redacted before it hits disk.")
