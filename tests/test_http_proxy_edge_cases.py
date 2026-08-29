"""
Covers the two real gaps filed as issues #2 and #3: the target server
being unreachable, and an SSE \\r\\n split exactly across a chunk-read
boundary. Both were found and fixed after the original HTTP proxy
tests only covered the happy path and the one error path (tool
failure).

Usage:
    .venv\\Scripts\\python.exe tests\\test_http_proxy_edge_cases.py
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.http_proxy import consume_sse_buffer  # noqa: E402

SESSIONS_DIR = ROOT / "sessions"
PYTHON = sys.executable


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_unreachable_target() -> None:
    """Issue #2: target unreachable used to crash the handler with an
    unhandled URLError, and the client got a dropped connection instead
    of any response at all."""
    dead_port = _free_port()  # nothing listening here
    proxy_port = _free_port()
    target_url = f"http://127.0.0.1:{dead_port}/mcp"

    before = set(SESSIONS_DIR.glob("edge-unreachable-*.jsonl")) if SESSIONS_DIR.exists() else set()

    proxy_proc = subprocess.Popen(
        [PYTHON, "-m", "greenlight.cli", "run", "--http", target_url,
         "--port", str(proxy_port), "--name", "edge-unreachable"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        # Check the proxy's own port is accepting connections with a raw
        # socket connect, not by sending a real request through it --
        # the target is deliberately dead here, so any real request
        # would legitimately fail and get logged. Doing that repeatedly
        # as a "readiness check" pollutes the count this test is trying
        # to verify. Found this the hard way: first version of this test
        # sent real requests to check readiness and got 14 proxy_error
        # entries instead of 1.
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", proxy_port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)

        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/mcp", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected a 502, got a normal response")
        except urllib.error.HTTPError as e:
            assert e.code == 502, f"expected 502, got {e.code}"
            payload = json.loads(e.read())
            assert payload["error"]["code"] == -32000
            print(f"client got a clean 502 with a parseable JSON-RPC error body: {payload['error']['message']}")
    finally:
        proxy_proc.terminate()
        try:
            proxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy_proc.kill()

    after = set(SESSIONS_DIR.glob("edge-unreachable-*.jsonl"))
    new_logs = after - before
    assert new_logs, "expected a session log to have been created"
    log_path = new_logs.pop()
    entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    proxy_errors = [e for e in entries if e.get("type") == "proxy_error"]
    assert len(proxy_errors) == 1, f"expected 1 proxy_error entry, got {len(proxy_errors)}"
    print(f"logged as a proxy_error entry, not silently dropped: {proxy_errors[0]['error']['message']}")

    from greenlight.stats import compute_stats
    stats = compute_stats(log_path)
    assert stats["failed"] is True
    assert stats["proxy_errors"] == 1
    print("stats correctly reports failed=True for a proxy_error")


def test_sse_crlf_split_across_chunk_boundary() -> None:
    """Issue #3: a \\r\\n split exactly across two chunk reads used to
    never get normalized, because each chunk was normalized
    independently before being appended to the buffer."""
    full_event = b'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\r\n\r\n'

    # split so the \r lands at the end of chunk 1 and the \n at the
    # start of chunk 2 -- the exact case the old per-chunk normalize
    # missed. found the split point that actually straddles a real
    # \r\n in the payload, not just any arbitrary midpoint.
    split_at = full_event.index(b"\r\n\r\n") + 1  # right after the first \r
    chunk1, chunk2 = full_event[:split_at], full_event[split_at:]
    assert chunk1.endswith(b"\r") and chunk2.startswith(b"\n"), "test setup didn't actually split a \\r\\n"

    buffer = b""
    events, buffer = consume_sse_buffer(buffer, chunk1)
    assert events == [], "shouldn't have a complete event yet, still mid-boundary"

    events, buffer = consume_sse_buffer(buffer, chunk2)
    assert len(events) == 1, f"expected the event to be recognized once the boundary is crossed, got {events}"
    payload = json.loads(events[0])
    assert payload["id"] == 1
    print(f"cross-chunk-boundary \\r\\n correctly joined and parsed: {events[0]}")


if __name__ == "__main__":
    test_unreachable_target()
    test_sse_crlf_split_across_chunk_boundary()
    print("\nALL CHECKS PASSED")
