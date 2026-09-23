"""
greenlight wrap is read-only by design -- it finds MCP client configs and
prints what a wrapped entry would look like, but never writes. These
tests only exercise that: config discovery against temp files (never a
real Claude Desktop / Claude Code config on the test machine) and the
pure entry-rewriting logic against hand-built dicts.

Usage:
    .venv\\Scripts\\python.exe tests\\test_wrap.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.wrap import (  # noqa: E402
    find_configs,
    format_suggestions,
    is_already_wrapped,
    load_servers,
    wrapped_entry,
)


def test_wrapped_entry_rewrites_command_and_keeps_other_fields() -> None:
    entry = {
        "command": "npx",
        "args": ["-y", "@some/server"],
        "env": {"API_KEY": "secret"},
    }
    wrapped = wrapped_entry("myserver", entry)
    assert wrapped is not None
    assert wrapped["command"] == sys.executable
    assert wrapped["args"][:5] == ["-m", "greenlight.cli", "run", "--name", "myserver"]
    assert wrapped["args"][5] == "--"
    assert wrapped["args"][6:] == ["npx", "-y", "@some/server"]
    # env and any other fields must survive untouched
    assert wrapped["env"] == {"API_KEY": "secret"}
    print("wrapped_entry: ok (command/args rewritten, other fields preserved)")


def test_wrapped_entry_none_for_url_based_server() -> None:
    entry = {"url": "https://example.com/mcp"}
    assert wrapped_entry("remote", entry) is None
    print("wrapped_entry: ok (no command field -> None, not a crash)")


def test_already_wrapped_detected_and_skipped() -> None:
    entry = {
        "command": sys.executable,
        "args": ["-m", "greenlight.cli", "run", "--name", "x", "--", "npx", "-y", "@some/server"],
    }
    assert is_already_wrapped(entry) is True
    assert wrapped_entry("x", entry) is None
    print("is_already_wrapped: ok (won't double-wrap)")


def test_format_suggestions_never_touches_disk() -> None:
    servers = {
        "add": {"command": "npx", "args": ["-y", "@some/server"]},
        "remote": {"url": "https://example.com/mcp"},
        "already-done": {
            "command": sys.executable,
            "args": ["-m", "greenlight.cli", "run", "--name", "already-done", "--", "npx"],
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        fake_path = Path(tmp) / "config.json"  # never written to -- just a label
        report = format_suggestions(fake_path, servers)
        assert not fake_path.exists(), "format_suggestions must never write to disk"

    assert "add:" in report
    assert "remote: no \"command\" field" in report
    assert "already-done: already wrapped" in report
    print("format_suggestions: ok (all three cases labeled correctly, nothing written)")


def test_find_configs_only_returns_files_that_exist() -> None:
    # known=[] isolates this from whatever's actually installed on the
    # machine running the test (e.g. a real Claude Desktop config) --
    # this test is only about the .mcp.json / existence-filtering logic.
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        # no .mcp.json here -- must not invent one
        assert find_configs(cwd, known=[]) == []

        mcp_json = cwd / ".mcp.json"
        mcp_json.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        found = find_configs(cwd, known=[])
        assert mcp_json.resolve() in [p.resolve() for p in found]

        # a known-location candidate that doesn't exist must be silently
        # skipped, not raise or get returned
        missing = cwd / "does-not-exist" / "config.json"
        found = find_configs(cwd, known=[missing])
        assert missing.resolve() not in [p.resolve() for p in found]
    print("find_configs: ok (only reports files that actually exist)")


def test_load_servers_reports_bad_json_clearly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "broken.json"
        bad.write_text("{not valid json", encoding="utf-8")
        try:
            load_servers(bad)
            assert False, "expected ValueError for invalid JSON"
        except ValueError as e:
            assert "not valid JSON" in str(e)

        no_servers = Path(tmp) / "no_servers.json"
        no_servers.write_text(json.dumps({"somethingElse": True}), encoding="utf-8")
        try:
            load_servers(no_servers)
            assert False, "expected ValueError for missing mcpServers"
        except ValueError as e:
            assert "mcpServers" in str(e)
    print("load_servers: ok (bad JSON and missing mcpServers both reported, not crashed)")


if __name__ == "__main__":
    test_wrapped_entry_rewrites_command_and_keeps_other_fields()
    test_wrapped_entry_none_for_url_based_server()
    test_already_wrapped_detected_and_skipped()
    test_format_suggestions_never_touches_disk()
    test_find_configs_only_returns_files_that_exist()
    test_load_servers_reports_bad_json_clearly()
    print("\nALL CHECKS PASSED -- wrap is read-only and its suggestion logic is correct.")
