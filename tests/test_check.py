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


def test_slow_initialize_is_startup_not_a_slow_call() -> None:
    # Found by running `check` on a real session against the official
    # reference server launched with `npx -y`: a cold cache made
    # 'initialize' take 11.8s, and the warning told the user to "consider
    # progress notifications", advice that makes no sense for startup.
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "slow-start.jsonl"
        entries = [
            {"ts": 1.0, "direction": "client->server", "parsed": True, "type": "request",
             "method": "initialize", "id": 1},
            {"ts": 12.8, "direction": "server->client", "parsed": True, "type": "result",
             "method": "initialize", "id": 1, "latency_ms": 11800.0},
        ]
        log.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        findings = check_session(log)
        assert [f.code for f in findings] == ["slow-start"], findings
        assert "progress notification" not in findings[0].message
        assert "npx" in findings[0].message
        assert cli_main(["check", str(log)]) == 0, "still just a warning"
    print("slow initialize: reported as slow-start with startup advice, not slow-call")


def test_top_level_schema_combinator() -> None:
    # One tool with a root-level anyOf/oneOf/allOf makes the Claude API
    # return a 400 for the whole request, and users can't tell which tool
    # did it. Goes through the real ProxySession.record() so the proxy's
    # extraction is covered too, not just the lint rule.
    from greenlight.proxy import ProxySession

    def tool(name, schema):
        return {"name": name, "description": "does a thing", "inputSchema": schema}

    tools_list = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [
        tool("fine", {"type": "object", "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "number"}]}}}),
        tool("bad_any", {"type": "object", "anyOf": [{"required": ["a"]}, {"required": ["b"]}]}),
        tool("bad_one", {"oneOf": [{"type": "object"}, {"type": "object"}], "type": "object"}),
    ]}}
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "combinator.jsonl"
        s = ProxySession(log)
        s.record("client->server", _msg(2, "tools/list").strip())
        s.record("server->client", json.dumps(tools_list))
        s.close()
        combos = [f for f in check_session(log) if f.code == "tool-schema-combinator"]
        flagged = sorted(next(n for n in ("bad_any", "bad_one") if repr(n) in f.message) for f in combos)
        assert flagged == ["bad_any", "bad_one"], [f.message for f in combos]
        assert all(f.severity == "error" for f in combos)
        assert not any("'fine'" in f.message for f in combos), "nested anyOf is valid and must not be flagged"
        assert cli_main(["check", str(log)]) == 1
    print("top-level oneOf/anyOf/allOf: ok (both bad tools flagged, nested anyOf left alone)")


if __name__ == "__main__":
    test_broken_server()
    test_clean_session()
    test_warnings_only_pass_unless_strict()
    test_slow_initialize_is_startup_not_a_slow_call()
    test_top_level_schema_combinator()
