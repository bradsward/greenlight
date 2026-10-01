"""
A session log's last line can be truncated if the process writing it
didn't exit cleanly -- a hard kill, an OOM kill, a crash, or power loss
can all interrupt a write mid-line. render.py's tail_file already skips
a line like that; compute_stats() and serve.py's tool functions used to
crash on it with a raw JSONDecodeError instead of reporting on everything
that *did* make it to disk intact.

Reproduced for real first: took an actual recorded session log, cut its
last line in half (no trailing newline, exactly what a mid-write kill
leaves behind), and ran `greenlight stats` on it -- got an unhandled
traceback. This is the fast, isolated version of that reproduction.

Usage:
    .venv\\Scripts\\python.exe tests\\test_corrupted_log_line.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.stats import compute_stats  # noqa: E402


def _write_log_with_truncated_last_line(path: Path) -> None:
    good_entries = [
        {"ts": 1.0, "direction": "client->server", "parsed": True,
         "type": "request", "method": "tools/call"},
        {"ts": 1.1, "direction": "server->client", "parsed": True,
         "type": "result", "method": "tools/call", "latency_ms": 5.0},
    ]
    lines = [json.dumps(e) for e in good_entries]
    # a plausible, fully-formed-looking line that gets cut off mid-write
    truncated = json.dumps({"ts": 1.2, "direction": "server->client", "parsed": True, "type": "result"})
    lines.append(truncated[: len(truncated) // 2])
    path.write_text("\n".join(lines), encoding="utf-8")  # deliberately no trailing newline


def test_compute_stats_survives_a_truncated_last_line() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "crashed-session.jsonl"
        _write_log_with_truncated_last_line(path)

        # the actual property under test: this must not raise
        stats = compute_stats(path)

        assert stats["total_messages"] == 2, stats
        assert stats["requests"] == 1, stats
        assert stats["results"] == 1, stats
        assert stats["corrupted_lines"] == 1, stats
        assert stats["failed"] is True, "a corrupted trailing line should fail the CI check too"
    print("compute_stats: ok (truncated last line skipped and counted, "
          "the other 2 valid entries still reported)")


def test_clean_log_reports_zero_corrupted_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clean-session.jsonl"
        path.write_text(json.dumps({"ts": 1.0, "direction": "client->server",
                                     "parsed": True, "type": "notification",
                                     "method": "notifications/initialized"}) + "\n",
                         encoding="utf-8")
        stats = compute_stats(path)
        assert stats["corrupted_lines"] == 0, stats
        assert stats["failed"] is False, stats
    print("compute_stats: ok (a clean log reports 0 corrupted lines, not a false failure)")


if __name__ == "__main__":
    test_compute_stats_survives_a_truncated_last_line()
    test_clean_log_reports_zero_corrupted_lines()
    print("\nALL CHECKS PASSED -- a truncated session log no longer crashes stats.")
