"""
Live trace viewer: renders a JSONL session log as a colorized, scrolling
trace -- green for a clean success, yellow for a slow-but-fine call, red
for anything that actually failed (transport-level or tool-level -- see
proxy.py's ProxySession.record for why those are tracked separately).

Prints incrementally, not as a redrawn table -- an unbounded trace is
closer to `tail -f` / `kubectl logs -f` than a fixed dashboard, and
that's the right model here: you want the scrollback, not just the
current state.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

SLOW_MS = 500  # a successful call slower than this still gets flagged

console = Console()


def _format_entry(entry: dict) -> tuple[str, str]:
    ts_struct = time.localtime(entry["ts"])
    ms = int((entry["ts"] % 1) * 1000)
    timestamp = f"{time.strftime('%H:%M:%S', ts_struct)}.{ms:03d}"
    arrow = "->" if entry.get("direction") == "client->server" else "<-"

    if not entry.get("parsed", True):
        raw = entry.get("raw", "")
        return f"{timestamp}  {arrow}  [unparsed] {raw[:60]}", "dim"

    kind = entry.get("type", "?")
    method = entry.get("method") or "?"

    if kind in ("request", "notification"):
        return f"{timestamp}  {arrow}  {method}", "white"

    latency = entry.get("latency_ms")
    latency_str = f"{latency:>8.2f}ms" if latency is not None else " " * 10

    if entry.get("tool_error"):
        return f"{timestamp}  {arrow}  {method:<24s} {latency_str}  FAILED (tool error)", "bold red"
    if kind in ("error", "proxy_error"):
        message = entry.get("error", {}).get("message", "?")
        return f"{timestamp}  {arrow}  {method:<24s} {latency_str}  FAILED: {message}", "bold red"
    if latency is not None and latency > SLOW_MS:
        return f"{timestamp}  {arrow}  {method:<24s} {latency_str}  ok (slow)", "yellow"
    return f"{timestamp}  {arrow}  {method:<24s} {latency_str}  ok", "green"


def tail_file(path: Path, follow: bool = False) -> None:
    console.print(f"[bold]watching[/bold] {path}")
    console.print(f"[dim]-> client to server   <- server to client[/dim]\n")

    with open(path, "r", encoding="utf-8") as f:
        while True:
            line = f.readline()
            if not line:
                if not follow:
                    break
                time.sleep(0.1)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            text, style = _format_entry(entry)
            console.print(text, style=style)


def latest_session(sessions_dir: Path) -> Optional[Path]:
    if not sessions_dir.exists():
        return None
    files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None
