"""
Session logs hold more than counts: tool error text, and the raw text of
anything a server prints to stdout (which can include secrets). They now
live in a fixed per-user directory, so they must not be readable by other
local users. Checked on a real file written by a real ProxySession.

POSIX only -- Windows has no mode bits, and the home directory there is
already private to the user by ACL.

Usage:
    .venv\\Scripts\\python.exe tests\\test_log_permissions.py
"""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.proxy import ProxySession  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # a directory greenlight has to create itself, like ~/.greenlight/sessions
        log_path = Path(tmp) / "fresh" / "sessions" / "s.jsonl"
        session = ProxySession(log_path)
        assert session.recording
        session.record("server->client", "SECRET_TOKEN printed to stdout by a noisy server")
        session.record("client->server", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
        session.close()

        assert "SECRET_TOKEN" in log_path.read_text(encoding="utf-8")

        if os.name != "posix":
            print("log permissions: skipped (no POSIX mode bits on this platform), "
                  "write path still verified")
            return

        file_mode = stat.S_IMODE(log_path.stat().st_mode)
        dir_mode = stat.S_IMODE(log_path.parent.stat().st_mode)
        assert file_mode == 0o600, f"log file mode {oct(file_mode)}, want 0o600"
        assert dir_mode == 0o700, f"log dir mode {oct(dir_mode)}, want 0o700"
    print("log permissions: ok (file 0600, directory 0700)")


if __name__ == "__main__":
    main()
