"""
HTTP-layer rejections are invisible in a JSON-RPC trace: a 401 from an
expired token never becomes a JSON-RPC error, so clients just say "failed
to connect". Before this, an empty-body 401 wasn't recorded at all and a
401 with a body showed up as an "unparsed" line with no status.

Real target (a stdlib HTTP server that rejects in several ways), real
proxy subprocess, real client. A JSON-RPC error that merely rides on a 4xx
(the MCP spec does this) must keep being recorded as a normal JSON-RPC
error, not double-counted as an HTTP failure.

Usage:
    .venv\\Scripts\\python.exe tests\\test_http_rejections.py
"""
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.check import check_session  # noqa: E402
from greenlight.stats import compute_stats  # noqa: E402

PYTHON = sys.executable
WWW_AUTH = 'Bearer realm="mcp", resource_metadata="https://example.test/.well-known/oauth-protected-resource"'


class Target(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        mode = (body.get("params") or {}).get("mode")
        if mode == "empty401":
            self.send_response(401)
            self.send_header("WWW-Authenticate", WWW_AUTH)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "html403":
            payload = b"<html><body>Forbidden by gateway</body></html>"
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if mode == "jsonrpc400":
            payload = json.dumps({"jsonrpc": "2.0", "id": body.get("id"),
                                  "error": {"code": -32602, "message": "bad params"}}).encode()
            self.send_response(400)
        else:
            payload = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {}}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(port: int, msg_id: int, mode: str) -> tuple[int, bytes, dict]:
    body = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": "ping", "params": {"mode": mode}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def main() -> None:
    target_port, proxy_port = _free_port(), _free_port()
    target = ThreadingHTTPServer(("127.0.0.1", target_port), Target)
    threading.Thread(target=target.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as log_dir:
        proxy = subprocess.Popen(
            [PYTHON, "-m", "greenlight.cli", "run", "--http", f"http://127.0.0.1:{target_port}/mcp",
             "--port", str(proxy_port), "--name", "rejections", "--log-dir", log_dir],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", proxy_port), timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.2)

            # the client must still get the real status, headers and body
            status, body, headers = _post(proxy_port, 1, "empty401")
            assert status == 401 and body == b"", (status, body)
            assert headers.get("WWW-Authenticate") == WWW_AUTH, headers
            status, body, _ = _post(proxy_port, 2, "html403")
            assert status == 403 and b"Forbidden by gateway" in body, (status, body)
            status, body, _ = _post(proxy_port, 3, "jsonrpc400")
            assert status == 400 and json.loads(body)["error"]["message"] == "bad params"
            status, _, _ = _post(proxy_port, 4, "ok")
            assert status == 200
            print("client sees the real status, headers and body for every case")
            time.sleep(0.5)
        finally:
            proxy.terminate()
            proxy.wait(timeout=10)
            target.shutdown()

        (log,) = Path(log_dir).glob("rejections-*.jsonl")
        entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]

        http_errors = [e for e in entries if e.get("http_status")]
        by_status = {e["http_status"]: e["error"]["message"] for e in http_errors}
        assert sorted(by_status) == [401, 403], f"expected only 401 and 403 recorded, got {by_status}"
        assert "WWW-Authenticate: Bearer" in by_status[401], by_status[401]
        assert "token expired" in by_status[401], by_status[401]
        assert "Forbidden by gateway" in by_status[403], by_status[403]
        print("401 (empty body) and 403 (HTML body) are recorded with status, header and snippet")

        assert not [e for e in entries if not e.get("parsed", True)], \
            "an HTTP error body must not be logged as an 'unparsed' stdout-style line"
        rpc_errors = [e for e in entries if e.get("type") == "error"]
        assert len(rpc_errors) == 1 and rpc_errors[0]["error"]["message"] == "bad params", rpc_errors
        print("a JSON-RPC error riding on a 400 stays a normal JSON-RPC error, not double-counted")

        stats = compute_stats(log)
        assert stats["failed"] and stats["proxy_errors"] == 2, stats
        codes = [f.code for f in check_session(log)]
        assert codes.count("http-auth-rejected") == 2, codes
        assert "stdout-pollution" not in codes, "an HTTP error page is not stdout pollution"
        print("stats fails the session and check reports http-auth-rejected for both")

    print("\nALL CHECKS PASSED -- HTTP-layer rejections are visible, JSON-RPC errors unchanged.")


if __name__ == "__main__":
    main()
