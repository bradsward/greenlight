"""
greenlight check against a real session recorded through the real proxy:
a deliberately broken server (tests/bad_fixture_server.py) must produce
exactly the findings it was built to trigger, and a clean session
(examples/demo-session.jsonl) must produce none.

Usage:
    .venv\\Scripts\\python.exe tests\\test_check.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.check import check_session  # noqa: E402
from greenlight.cli import main as cli_main  # noqa: E402

PYTHON = sys.executable


def _msg(msg_id, method, params=None) -> str:
    m = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        m["id"] = msg_id
    if params is not None:
        m["params"] = params
    return json.dumps(m) + "\n"


def test_broken_server() -> None:
    client_input = (
        _msg(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "0"}})
        + _msg(None, "notifications/initialized")
        + _msg(2, "tools/list")
        + _msg(3, "tools/call", {"name": "ok_tool", "arguments": {}})
    )
    with tempfile.TemporaryDirectory() as log_dir:
        subprocess.run(
            [PYTHON, "-m", "greenlight.cli", "run", "--name", "bad", "--log-dir", log_dir, "--",
             PYTHON, str(ROOT / "tests" / "bad_fixture_server.py")],
            input=client_input, capture_output=True, text=True, timeout=30, check=True,
        )
        (log,) = Path(log_dir).glob("bad-*.jsonl")
        findings = check_session(log)
        codes = sorted(f.code for f in findings)
        expected = sorted([
            "stdout-pollution",
            "tool-no-input-schema",
            "tool-schema-not-object",
            "tool-no-description",
            "tool-name-portability",
            "tool-duplicate-name",
            "unanswered-request",
        ])
        assert codes == expected, f"\n got: {codes}\nwant: {expected}"
        unanswered = next(f for f in findings if f.code == "unanswered-request")
        assert "tools/call" in unanswered.message, unanswered.message
        assert cli_main(["check", str(log)]) == 1, "errors must exit non-zero"
    print(f"broken server: all {len(expected)} expected findings, exit code 1")


def test_clean_session() -> None:
    path = ROOT / "examples" / "demo-session.jsonl"
    findings = check_session(path)
    assert findings == [], findings
    assert cli_main(["check", str(path)]) == 0
    assert cli_main(["check", "--strict", str(path)]) == 0
    print("clean session: no findings, exit code 0")


def test_warnings_only_pass_unless_strict() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "warn.jsonl"
        entries = [
            {"ts": 1.0, "direction": "client->server", "parsed": True, "type": "request",
             "method": "initialize", "id": 1},
            {"ts": 1.1, "direction": "server->client", "parsed": True, "type": "result",
             "method": "initialize", "id": 1, "latency_ms": 100.0},
            {"ts": 2.0, "direction": "client->server", "parsed": True, "type": "request",
             "method": "tools/call", "id": 2},
            {"ts": 9.0, "direction": "server->client", "parsed": True, "type": "result",
             "method": "tools/call", "id": 2, "latency_ms": 7000.0},
        ]
        log.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        assert [f.code for f in check_session(log)] == ["slow-call"]
        assert cli_main(["check", str(log)]) == 0
        assert cli_main(["check", "--strict", str(log)]) == 1
    print("warnings: exit 0 by default, exit 1 with --strict")


if __name__ == "__main__":
    test_broken_server()
    test_clean_session()
    test_warnings_only_pass_unless_strict()
