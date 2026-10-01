"""
Aggregate stats over a session log. Two audiences: a human wanting a
quick health check without reading a full trace, and a CI pipeline that
just wants an exit code -- "did anything in this MCP session fail."
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Optional


def compute_stats(path: Path) -> dict:
    # A session log's last line can be truncated -- `run_proxy`'s process
    # getting SIGKILLed, an OOM kill, a crash, or power loss can all leave
    # a partial write behind (the writer locks around one line at a time,
    # but a hard kill doesn't care what it interrupts). `tail_file`
    # (render.py) already skips a line like that instead of raising;
    # compute_stats used to just crash with a raw JSONDecodeError traceback
    # on the exact failure this tool exists to report on cleanly. Skipping
    # it and counting it, same as render.py does, means a crashed session
    # still gets a real stats summary for everything that *did* make it to
    # disk, instead of losing the whole report over one bad line.
    corrupted = 0
    entries = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            corrupted += 1

    requests = [e for e in entries if e.get("type") == "request"]
    notifications = [e for e in entries if e.get("type") == "notification"]
    results = [e for e in entries if e.get("type") == "result"]
    transport_errors = [e for e in entries if e.get("type") == "error"]
    tool_errors = [e for e in results if e.get("tool_error")]
    # Distinct from transport_errors: the target never responded at all
    # (connection refused, unreachable), so there's no JSON-RPC error
    # object to point at, just the proxy's own record of the failure.
    proxy_errors = [e for e in entries if e.get("type") == "proxy_error"]
    unparsed = [e for e in entries if not e.get("parsed", True)]

    # The actual reasons behind a failure, not just the counts -- a
    # transport error and a proxy error both carry a message already
    # (msg["error"]["message"]), and a tool error now carries the text MCP
    # itself gave for the failure (see proxy.py's _tool_error_text). Surfaced
    # here so `greenlight stats` can tell you *why* a CI run failed without
    # having to go dig through the full trace.
    failure_messages = [
        e["error"]["message"]
        for e in transport_errors + proxy_errors
        if e.get("error", {}).get("message")
    ] + [
        e["tool_error_message"]
        for e in tool_errors
        if e.get("tool_error_message")
    ]

    latencies = [e["latency_ms"] for e in results if "latency_ms" in e]

    by_method: dict[str, list[float]] = {}
    for e in results:
        method = e.get("method") or "?"
        if "latency_ms" in e:
            by_method.setdefault(method, []).append(e["latency_ms"])

    return {
        "total_messages": len(entries),
        "requests": len(requests),
        "notifications": len(notifications),
        "results": len(results),
        "transport_errors": len(transport_errors),
        "tool_errors": len(tool_errors),
        "proxy_errors": len(proxy_errors),
        "unparsed_lines": len(unparsed),
        "corrupted_lines": corrupted,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "median": round(median(latencies), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
        "by_method": {
            method: {"count": len(lats), "median_ms": round(median(lats), 2)}
            for method, lats in sorted(by_method.items())
        },
        # A corrupted trailing line usually means the process that was
        # writing it didn't exit cleanly -- worth failing a CI check over,
        # same as any other real failure this reports.
        "failed": bool(transport_errors or tool_errors or proxy_errors or corrupted),
        "failure_messages": failure_messages,
    }


def format_stats(stats: dict, path: Path) -> str:
    lines = [f"session: {path}", ""]
    lines.append(f"  {stats['total_messages']} messages "
                  f"({stats['requests']} requests, {stats['notifications']} notifications, "
                  f"{stats['results']} results)")

    lat = stats["latency_ms"]
    if lat["median"] is not None:
        lines.append(f"  latency: min {lat['min']}ms  median {lat['median']}ms  max {lat['max']}ms")

    if stats["by_method"]:
        lines.append("\n  by method:")
        for method, m in stats["by_method"].items():
            lines.append(f"    {method:<28s} {m['count']:>4d} calls   median {m['median_ms']}ms")

    lines.append("")
    if stats["failed"]:
        lines.append(f"  FAILED -- {stats['transport_errors']} transport error(s), "
                      f"{stats['tool_errors']} tool error(s), "
                      f"{stats['proxy_errors']} proxy error(s, target unreachable)")
        for msg in stats["failure_messages"][:5]:
            lines.append(f"    - {msg}")
        if stats["corrupted_lines"]:
            lines.append(f"    - {stats['corrupted_lines']} corrupted/truncated log line(s) -- "
                          f"the process writing this log likely didn't exit cleanly")
    else:
        lines.append("  no failures")

    if stats["unparsed_lines"]:
        lines.append(f"  ({stats['unparsed_lines']} unparsed/non-JSON-RPC lines -- see notes/day3.md)")

    return "\n".join(lines)
