"""
The core of Greenlight: a transparent stdio proxy for MCP servers.

Sits between a real MCP client (Claude Desktop, Claude Code, etc.) and a
real MCP server. Every byte that would have flowed directly between them
still does -- this only *also* copies each line into a structured log.

The one rule that matters more than anything else in this file: nothing
except the child process's own stdout bytes may ever reach our stdout.
Any UI or logging written there would corrupt the JSON-RPC stream the
real client is expecting to parse cleanly. Logging goes to a JSONL file
on disk (stdout is sacred; stderr is not -- the stdio MCP transport never
uses stderr for protocol traffic, so a status line there is safe).
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

SESSIONS_DIR = Path.cwd() / "sessions"


def _tool_error_text(result: dict) -> str:
    """A tool-error result's `content` is a list of content blocks -- almost
    always one or more {"type": "text", "text": "..."} items carrying the
    actual explanation (e.g. "division by zero", an API's own error
    message). Until now that text was thrown away and only the isError
    flag was kept, so `tail` could say a call failed but never why.
    Real example, from this project's own boom() fixture tool: 'Error
    executing tool boom: this tool always fails, on purpose'."""
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    return " ".join(parts)


@dataclass
class _PendingRequest:
    method: str
    sent_at: float


class ProxySession:
    """Parses each relayed line as JSON-RPC and writes one structured
    record per message to a JSONL log. Correlates responses back to the
    request that caused them (by id) so latency and method name are
    known even on the response side, where the raw JSON-RPC message
    alone doesn't carry the method."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self._pending: dict[object, _PendingRequest] = {}
        self._lock = threading.Lock()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(log_path, "a", encoding="utf-8", buffering=1)

    def record(self, direction: str, raw_line: str) -> None:
        line = raw_line.strip()
        if not line:
            return
        ts = time.time()
        entry: dict = {"ts": ts, "direction": direction}

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            # Not every line a server writes to stdout is guaranteed to be
            # a clean JSON-RPC message in practice (stray prints, partial
            # writes). Relay already happened upstream of this function --
            # log it as unparsed rather than dropping it or crashing.
            entry["parsed"] = False
            entry["raw"] = line[:500]
            self._write(entry)
            return

        if not isinstance(msg, dict):
            # json.loads succeeds for any valid JSON value, not just
            # objects -- a bare "null", "42", "true", or "[1,2,3]" is
            # valid JSON and parses fine, but msg.get(...) below would
            # crash with AttributeError since none of those are dicts.
            # Reproduced for real: a literal `null` POST body took down
            # the HTTP proxy's request handler with an unhandled
            # exception (the stdio side's caller happens to swallow
            # exceptions from record(), so there it silently dropped the
            # entry instead of crashing -- neither is the right
            # behavior). Treated the same way invalid JSON already is:
            # it's not a usable JSON-RPC message either way, logged as
            # such rather than crashing or vanishing.
            entry["parsed"] = False
            entry["raw"] = line[:500]
            self._write(entry)
            return

        entry["parsed"] = True
        msg_id = msg.get("id")
        method = msg.get("method")

        if method is not None:
            entry["type"] = "request" if msg_id is not None else "notification"
            entry["method"] = method
            if msg_id is not None:
                with self._lock:
                    self._pending[msg_id] = _PendingRequest(method=method, sent_at=ts)
        else:
            entry["type"] = "error" if "error" in msg else "result"
            pending = None
            if msg_id is not None:
                with self._lock:
                    pending = self._pending.pop(msg_id, None)
            if pending is not None:
                entry["method"] = pending.method
                entry["latency_ms"] = round((ts - pending.sent_at) * 1000, 2)
            if "error" in msg:
                entry["error"] = msg["error"]
            elif isinstance(msg.get("result"), dict) and msg["result"].get("isError"):
                # MCP nests tool-execution failures inside a normal JSON-RPC
                # "result" (isError: true), separate from transport-level
                # JSON-RPC errors -- a failed tool call is NOT `"error" in msg`.
                # Found by testing against a real server whose tool
                # deliberately raises: it logged as an ordinary success
                # until this check was added. This is exactly the kind of
                # failure a trace viewer exists to surface, so it gets its
                # own flag rather than being indistinguishable from a
                # normal result.
                entry["tool_error"] = True
                text = _tool_error_text(msg["result"])
                if text:
                    entry["tool_error_message"] = text[:500]

        self._write(entry)

    def record_proxy_error(self, message: str) -> None:
        """For failures where no JSON-RPC response ever came back at all
        (target unreachable, connection refused, timed out) -- distinct
        from a transport-level JSON-RPC error (the target DID respond,
        just with an error object) and from a tool_error (the target
        responded, the tool itself failed). This is "nothing came back",
        which is a different failure mode the proxy has to originate
        itself, not just relay."""
        entry = {
            "ts": time.time(),
            "direction": "server->client",
            "parsed": True,
            "type": "proxy_error",
            "error": {"message": message},
        }
        self._write(entry)

    def _write(self, entry: dict) -> None:
        # Locked, unlike the rest of this class's opportunistic locking
        # (self._lock elsewhere only guards the _pending dict). The
        # stdio proxy only ever has one caller for this. The HTTP proxy
        # uses ThreadingHTTPServer, so multiple real client connections
        # can call record() concurrently, and this is a shared file
        # handle with buffering=1 (line-buffered), meaning every call
        # here triggers an actual flush syscall -- and Python can
        # release the GIL during a blocking syscall, letting another
        # thread's write interleave. Fired 60 concurrent requests across
        # 20 threads at the HTTP proxy and didn't reproduce corruption,
        # but "didn't reproduce it in one run" isn't the same as "can't
        # happen" for a race this specific -- the fix is one line and
        # free, no reason to leave a real architectural gap open just
        # because it didn't manifest today.
        with self._lock:
            self._log_file.write(json.dumps(entry) + "\n")
            self._log_file.flush()

    def close(self) -> None:
        self._log_file.close()


def _pump(src, dst, on_line: Callable[[str], None]) -> None:
    """Read lines from src, relay them byte-for-byte to dst immediately,
    then hand off to on_line for logging. Relay happens first and always
    -- a logging exception must never be able to break the proxied
    stream. Runs in its own thread; one of these per direction."""
    try:
        for raw in iter(src.readline, b""):
            try:
                dst.write(raw)
                dst.flush()
            except (BrokenPipeError, OSError):
                break
            try:
                on_line(raw.decode("utf-8", errors="replace"))
            except Exception:
                pass
    finally:
        try:
            dst.flush()
        except (BrokenPipeError, OSError):
            pass


def run_proxy(command: list[str], session_name: Optional[str] = None) -> int:
    name = session_name or (Path(command[0]).stem if command else "session")
    log_path = SESSIONS_DIR / f"{name}-{int(time.time())}-{uuid.uuid4().hex[:6]}.jsonl"
    session = ProxySession(log_path)

    print(f"greenlight: recording to {log_path}", file=sys.stderr)
    print(f"greenlight: run `greenlight tail {log_path}` in another terminal to watch live",
          file=sys.stderr)

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,  # inherited -- the server's own error output isn't ours to hide
        bufsize=0,    # no extra buffering beyond the pipe itself; latency matters here
    )
    assert proc.stdin is not None and proc.stdout is not None

    t_in = threading.Thread(
        target=_pump,
        args=(sys.stdin.buffer, proc.stdin, lambda line: session.record("client->server", line)),
        daemon=True,
    )
    t_out = threading.Thread(
        target=_pump,
        args=(proc.stdout, sys.stdout.buffer, lambda line: session.record("server->client", line)),
        daemon=True,
    )
    t_in.start()
    t_out.start()

    try:
        returncode = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        returncode = proc.wait()
    finally:
        t_out.join(timeout=2)
        session.close()

    return returncode
