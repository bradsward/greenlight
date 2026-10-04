"""
When the client closes the proxy's stdin, the proxy has to close the
server's stdin too. That EOF is how the MCP stdio transport tells a
server to shut down. Before this was fixed, the proxy relayed every
message but never passed the EOF on, so the server kept waiting for
input and `greenlight run` hung forever on every clean client shutdown.

Usage:
    .venv\\Scripts\\python.exe tests\\test_stdin_eof.py
"""
import subprocess
import sys
import tempfile

PYTHON = sys.executable
# A minimal stand-in for a stdio server: echoes each line, exits on EOF.
ECHO_SERVER = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line); sys.stdout.flush()\n"


def main() -> None:
    msg = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
    with tempfile.TemporaryDirectory() as log_dir:
        try:
            result = subprocess.run(
                [PYTHON, "-m", "greenlight.cli", "run", "--log-dir", log_dir, "--",
                 PYTHON, "-c", ECHO_SERVER],
                input=msg, capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            raise AssertionError("proxy hung after client closed stdin -- EOF not passed to server")
    assert result.returncode == 0, result
    assert result.stdout == msg, result.stdout
    print("client EOF: passed through to the server, proxy exited cleanly")


if __name__ == "__main__":
    main()
