"""
greenlight check -- lint a recorded session for protocol and server bugs.

`stats` answers "did any call fail". This answers a different question:
"is this server doing something wrong that will bite a real client" --
the kind of problem that doesn't show up as a failed call at all. The
most common one: a server printing log output to stdout, which in the
stdio transport is reserved for JSON-RPC. Depending on the client that
gets silently dropped, breaks parsing, or kills the connection, and from
the server author's side it just looks like "the client is flaky".

Errors exit non-zero (CI-usable, same as `stats`); warnings don't unless
--strict.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

SLOW_WARN_MS = 5000

# The MCP spec allows more than this (up to 128 chars, plus "."), but
# common model APIs that clients forward tool definitions to only accept
# this pattern, and a client may reject or rename tools that don't fit.
PORTABLE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class Finding:
    severity: str  # "error" or "warning"
    code: str
    message: str


def _read(path: Path) -> tuple[list[dict], int]:
    entries, corrupted = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            corrupted += 1
    return entries, corrupted


def _key(msg_id: object) -> str:
    # JSON-RPC ids can be numbers or strings; 1 and "1" are different ids.
    return json.dumps(msg_id)


def check_session(path: Path) -> list[Finding]:
    entries, corrupted = _read(path)
    findings: list[Finding] = []

    # --- stdout pollution ---------------------------------------------------
    polluted = [e for e in entries
                if not e.get("parsed", True) and e.get("direction") == "server->client"]
    if polluted:
        sample = polluted[0].get("raw", "")[:80]
        findings.append(Finding(
            "error", "stdout-pollution",
            f"server wrote {len(polluted)} non-JSON-RPC line(s) to stdout, e.g. {sample!r}. "
            f"In the stdio transport stdout is for protocol messages only -- send logs and "
            f"prints to stderr. Clients may drop these lines, fail to parse, or disconnect.",
        ))
    client_junk = [e for e in entries
                   if not e.get("parsed", True) and e.get("direction") == "client->server"]
    if client_junk:
        findings.append(Finding(
            "warning", "client-non-jsonrpc",
            f"client sent {len(client_junk)} line(s) that weren't JSON-RPC messages",
        ))

    if corrupted:
        findings.append(Finding(
            "warning", "truncated-log",
            f"{corrupted} corrupted/truncated log line(s) -- the proxy likely didn't exit cleanly, "
            f"so this check may be missing the end of the session",
        ))

    # --- lifecycle ----------------------------------------------------------
    client_requests = [e for e in entries
                       if e.get("type") == "request" and e.get("direction") == "client->server"]
    if client_requests and client_requests[0].get("method") != "initialize":
        findings.append(Finding(
            "warning", "no-initialize",
            f"first client request was {client_requests[0].get('method')!r}, not 'initialize' "
            f"(or the session log started mid-session)",
        ))

    # --- request/response pairing (needs ids, logged since 0.5.0) -----------
    if any("id" in e for e in entries):
        open_requests: dict[tuple[str, str], dict] = {}
        for e in entries:
            if "id" not in e:
                continue
            direction = e.get("direction")
            if e.get("type") == "request":
                open_requests[(direction, _key(e["id"]))] = e
            elif e.get("type") in ("result", "error"):
                requester = "server->client" if direction == "client->server" else "client->server"
                if open_requests.pop((requester, _key(e["id"])), None) is None:
                    findings.append(Finding(
                        "error", "orphan-response",
                        f"{direction} response for id {e['id']!r}, which no request used "
                        f"(or which was already answered)",
                    ))
        for (direction, _), req in open_requests.items():
            who = "server" if direction == "client->server" else "client"
            findings.append(Finding(
                "warning", "unanswered-request",
                f"{req.get('method')!r} (id {req['id']!r}) never got a response from the {who}",
            ))

    # --- slow calls ---------------------------------------------------------
    for e in entries:
        latency = e.get("latency_ms")
        if latency is not None and latency >= SLOW_WARN_MS:
            findings.append(Finding(
                "warning", "slow-call",
                f"{e.get('method')!r} took {latency / 1000:.1f}s -- clients often time out "
                f"long-running calls; consider progress notifications",
            ))

    # --- tool definitions (from tools/list results) -------------------------
    linted: set[str] = set()
    for e in entries:
        for tool in e.get("tools") or []:
            if tool.get("invalid"):
                findings.append(Finding("error", "tool-invalid", "tools/list contained a non-object entry"))
                continue
            name = tool.get("name")
            if not isinstance(name, str) or not name:
                findings.append(Finding("error", "tool-no-name", "a tool in tools/list has no name"))
                continue
            if name in linted:
                continue  # the same tool listed again in a later tools/list call
            linted.add(name)
            if not tool.get("has_input_schema"):
                findings.append(Finding(
                    "error", "tool-no-input-schema",
                    f"tool {name!r} has no inputSchema -- the spec requires one, even for a tool "
                    f"with no arguments ({{\"type\": \"object\"}})",
                ))
            elif tool.get("input_schema_type") != "object":
                findings.append(Finding(
                    "error", "tool-schema-not-object",
                    f"tool {name!r} inputSchema has type {tool.get('input_schema_type')!r}; "
                    f"it must be \"object\"",
                ))
            if not tool.get("description"):
                findings.append(Finding(
                    "warning", "tool-no-description",
                    f"tool {name!r} has no description -- the model picks tools by description, "
                    f"so it may never call this one",
                ))
            if not PORTABLE_TOOL_NAME.match(name):
                findings.append(Finding(
                    "warning", "tool-name-portability",
                    f"tool name {name!r} isn't ^[A-Za-z0-9_-]{{1,64}}$ -- valid MCP, but some "
                    f"clients and model APIs reject or rewrite names outside that pattern",
                ))
    # Per tools/list response, not across the session: a client calling
    # tools/list twice legitimately sees every name twice.
    for e in entries:
        names = [t.get("name") for t in e.get("tools") or [] if isinstance(t.get("name"), str)]
        dupes = sorted({n for n in names if names.count(n) > 1})
        for n in dupes:
            findings.append(Finding(
                "error", "tool-duplicate-name",
                f"tool name {n!r} appears more than once in a single tools/list response",
            ))

    order = {"error": 0, "warning": 1}
    findings.sort(key=lambda f: order[f.severity])
    return findings


def findings_json(findings: list[Finding]) -> str:
    return json.dumps([asdict(f) for f in findings], indent=2)


def print_findings(findings: list[Finding], path: Path, console) -> None:
    from rich.markup import escape
    console.print(f"session: {path}\n")
    if not findings:
        console.print("  [green]no problems found[/green]")
        return
    for f in findings:
        style = "bold red" if f.severity == "error" else "yellow"
        console.print(f"  [{style}]{f.severity:<7s}[/{style}] [dim]{f.code}[/dim]  {escape(f.message)}",
                      highlight=False)
    errors = sum(f.severity == "error" for f in findings)
    warnings = len(findings) - errors
    console.print(f"\n  {errors} error(s), {warnings} warning(s)")
