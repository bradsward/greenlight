"""
record()'s tool_error_message extraction, tested directly against
hand-crafted JSON-RPC lines rather than through a real MCP server.

This exists because test_proxy_e2e.py's end-to-end version of this check
turned out to be coupled to something outside this project's control: the
exact text the installed `mcp` SDK puts in result.content when a tool
raises varies by SDK version (one CI run got "Error executing tool boom",
another got "Error executing tool boom: this tool always fails, on
purpose" -- same underlying exception, different SDK-generated wrapper
text). That's a real gap in the test, not the feature: record() itself
just reads whatever content blocks are actually there, and that part
doesn't depend on the SDK at all. Pinning down the extraction logic here,
against inputs this project controls, is what the e2e test can't give us.

Usage:
    .venv\\Scripts\\python.exe tests\\test_tool_error_extraction.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.proxy import ProxySession  # noqa: E402


def _record_result(result: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "test.jsonl"
        session = ProxySession(log_path)
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
        session.record("server->client", line)
        session.close()
        entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(entries) == 1
        return entries[0]


def test_single_text_block() -> None:
    entry = _record_result({
        "content": [{"type": "text", "text": "division by zero"}],
        "isError": True,
    })
    assert entry["tool_error"] is True
    assert entry["tool_error_message"] == "division by zero"
    print("single text block: ok")


def test_multiple_text_blocks_joined() -> None:
    entry = _record_result({
        "content": [
            {"type": "text", "text": "first line"},
            {"type": "text", "text": "second line"},
        ],
        "isError": True,
    })
    assert entry["tool_error_message"] == "first line second line", entry["tool_error_message"]
    print("multiple text blocks: ok (joined)")


def test_non_text_blocks_skipped_not_crashed() -> None:
    # A real server can return image/resource blocks alongside text, or
    # (as an isError result specifically) sometimes no text at all --
    # extraction must degrade gracefully, never raise.
    entry = _record_result({
        "content": [
            {"type": "image", "data": "base64stuff", "mimeType": "image/png"},
            {"type": "text", "text": "the actual error"},
        ],
        "isError": True,
    })
    assert entry["tool_error_message"] == "the actual error", entry["tool_error_message"]
    print("mixed content blocks: ok (non-text skipped, text kept)")


def test_no_content_field() -> None:
    entry = _record_result({"isError": True})
    assert entry["tool_error"] is True
    assert "tool_error_message" not in entry
    print("missing content field: ok (flagged, no message, no crash)")


def test_long_message_truncated() -> None:
    entry = _record_result({
        "content": [{"type": "text", "text": "x" * 2000}],
        "isError": True,
    })
    assert len(entry["tool_error_message"]) == 500, len(entry["tool_error_message"])
    print("long message: ok (truncated to 500 chars, same as the unparsed-line path)")


if __name__ == "__main__":
    test_single_text_block()
    test_multiple_text_blocks_joined()
    test_non_text_blocks_skipped_not_crashed()
    test_no_content_field()
    test_long_message_truncated()
    print("\nALL CHECKS PASSED -- tool_error_message extraction verified independent of any MCP SDK version.")
