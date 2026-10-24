"""
`spawn npx ENOENT` / "Server disconnected" is the failure MCP users hit
most: the client launches the server with a smaller PATH than a terminal
has. Wrapped in greenlight, that used to end in a raw FileNotFoundError
traceback. It should say what happened and what to do (on stderr, where
clients capture a server's output), exit 127 like a shell, and be logged.

Usage:
    .venv\\Scripts\\python.exe tests\\test_missing_command.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.stats import compute_stats  # noqa: E402

PYTHON = sys.executable


def main() -> None:
    with tempfile.TemporaryDirectory() as log_dir:
        proc = subprocess.run(
            [PYTHON, "-m", "greenlight.cli", "run", "--name", "missing", "--log-dir", log_dir,
             "--", "definitely-not-a-real-mcp-server-command"],
            input=b"", capture_output=True, timeout=30,
        )
        err = proc.stderr.decode("utf-8", errors="replace")
        assert proc.returncode == 127, (proc.returncode, err)
        assert "Traceback" not in err, err
        assert "'definitely-not-a-real-mcp-server-command' was not found" in err, err
        assert "PATH" in err and "greenlight wrap" in err, err
        assert proc.stdout == b"", "stdout must stay clean: it belongs to the protocol"

        (log,) = Path(log_dir).glob("missing-*.jsonl")
        entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        assert [e["type"] for e in entries] == ["proxy_error"], entries
        assert "was not found" in entries[0]["error"]["message"]
        assert compute_stats(log)["failed"] is True
    print("missing command: ok (exit 127, clear PATH message on stderr, stdout clean, logged as a failure)")


if __name__ == "__main__":
    main()
