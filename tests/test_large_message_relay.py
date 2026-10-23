"""
A transparent proxy must not tax large messages. Found by running
greenlight against real servers and timing a 4 MB tool result: 2.26s
through the proxy against 0.08s direct. The child's stdout was a raw
unbuffered pipe, and readline() on a raw stream reads one byte per
syscall. Relayed bytes were always correct -- this was purely speed, but
big results (base64 screenshots, large file reads) are normal MCP
traffic, and the slowdown also inflated the latencies greenlight logged.

Measured as the *difference* between a tiny and a large message through
the same proxy, so interpreter startup (which varies a lot on CI) cancels
out. Before the fix that difference was ~4.4s for 8 MB; after, ~0.1s.

Usage:
    .venv\\Scripts\\python.exe tests\\test_large_message_relay.py
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PYTHON = sys.executable
BIG_MB = 8
MAX_EXTRA_SECONDS = 1.5

REQUEST = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call"}) + "\n"


def _child_code(size_bytes: int) -> str:
    return (
        "import sys, json\n"
        "sys.stdin.readline()\n"
        f"text = 'x' * {size_bytes}\n"
        "sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 1, "
        "'result': {'content': [{'type': 'text', 'text': text}]}}) + '\\n')\n"
        "sys.stdout.flush()\n"
    )


def _run(cmd: list[str]) -> tuple[float, bytes]:
    start = time.perf_counter()
    proc = subprocess.run(cmd, input=REQUEST.encode(), capture_output=True, timeout=120, check=True)
    return time.perf_counter() - start, proc.stdout


def main() -> None:
    big = BIG_MB * 1024 * 1024
    with tempfile.TemporaryDirectory() as log_dir:
        def proxied(size: int) -> list[str]:
            return [PYTHON, "-m", "greenlight.cli", "run", "--log-dir", log_dir, "--",
                    PYTHON, "-c", _child_code(size)]

        small_time, _ = _run(proxied(10))
        big_time, big_out = _run(proxied(big))
        _, direct_out = _run([PYTHON, "-c", _child_code(big)])

        assert big_out == direct_out, "relayed bytes differ from what the server wrote"
        assert len(big_out) > big, len(big_out)

        extra = big_time - small_time
        assert extra < MAX_EXTRA_SECONDS, (
            f"relaying {BIG_MB} MB cost {extra:.2f}s more than a tiny message "
            f"(limit {MAX_EXTRA_SECONDS}s) -- is the server's stdout read unbuffered again?"
        )

        # the big response must still have been parsed and logged, not skipped
        logs = sorted(Path(log_dir).glob("*.jsonl"))
        entries = [json.loads(line) for log in logs for line in log.read_text().splitlines() if line.strip()]
        assert any(e.get("type") == "result" and e.get("direction") == "server->client"
                   for e in entries), entries
    print(f"large message relay: ok ({BIG_MB} MB byte-identical, +{extra:.2f}s over a tiny message)")


if __name__ == "__main__":
    main()
