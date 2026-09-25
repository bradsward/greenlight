"""
Greenlight CLI entry point.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence

from rich.console import Console

from greenlight import __version__
from greenlight.banner import print_banner
from greenlight.http_proxy import run_http_proxy
from greenlight.proxy import SESSIONS_DIR, run_proxy
from greenlight.render import latest_session, tail_file
from greenlight.stats import compute_stats, format_stats


def _resolve(command: list[str]) -> list[str]:
    """Resolve command[0] through PATH (and PATHEXT on Windows) before
    handing it to subprocess. Without this, `greenlight run -- npx ...`
    fails on Windows with a confusing FileNotFoundError, because
    subprocess with shell=False doesn't apply PATHEXT resolution itself
    the way a real shell would -- "npx" on Windows is actually npx.cmd."""
    if not command:
        return command
    resolved = shutil.which(command[0])
    return [resolved, *command[1:]] if resolved else command


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="greenlight",
        description="See what your MCP server is actually doing.",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"greenlight {__version__}",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=False)

    run_p = subparsers.add_parser(
        "run",
        help="Run an MCP server through the proxy, recording every message.",
    )
    run_p.add_argument("--name", default=None, help="session name (defaults to the command's name)")
    run_p.add_argument(
        "--http", default=None, metavar="URL",
        help="proxy a Streamable HTTP MCP server at this URL instead of spawning a stdio process "
             "-- point your client at the local URL greenlight prints, not this one",
    )
    run_p.add_argument(
        "--port", type=int, default=8808,
        help="local port to listen on for --http mode (default: 8808)",
    )
    run_p.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="the real MCP server command, e.g. -- npx -y @some/mcp-server (ignored with --http)",
    )

    tail_p = subparsers.add_parser(
        "tail",
        help="View a recorded session's trace -- green for ok, yellow for slow, red for failed.",
    )
    tail_p.add_argument(
        "path", nargs="?", default=None,
        help="session log to view (defaults to the most recent one in ./sessions)",
    )
    tail_p.add_argument(
        "-f", "--follow", action="store_true",
        help="keep watching for new messages, like `tail -f` (use this while a session is still running)",
    )

    stats_p = subparsers.add_parser(
        "stats",
        help="Summarize a session: message counts, latency, and whether anything failed. "
             "Exits non-zero on failure -- usable as a CI check.",
    )
    stats_p.add_argument(
        "path", nargs="?", default=None,
        help="session log to summarize (defaults to the most recent one in ./sessions)",
    )
    stats_p.add_argument("--json", action="store_true", help="print machine-readable JSON instead")

    wrap_p = subparsers.add_parser(
        "wrap",
        help="Show how to point your real MCP client config at Greenlight. Read-only -- "
             "prints suggestions, never writes anything.",
    )
    wrap_p.add_argument(
        "path", nargs="?", default=None,
        help="a specific config file to check (defaults to searching known Claude Desktop, "
             "Claude Code, Cursor, and Windsurf locations)",
    )

    subparsers.add_parser(
        "serve",
        help="Expose this project's own session data as an MCP server, so an agent can query "
             "real trace/failure data directly instead of you relaying terminal output to it. "
             "Needs the optional `serve` extra: pip install greenlight-mcp[serve]",
    )

    args = parser.parse_args(argv)

    if args.cmd is None:
        print_banner(Console())
        parser.print_help()
        return 0

    if args.cmd == "run":
        if args.http:
            return run_http_proxy(args.http, port=args.port, session_name=args.name)
        command = list(args.command)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error(
                "no server command given -- e.g. `greenlight run -- npx -y @some/mcp-server`, "
                "or `greenlight run --http <url>` for a Streamable HTTP server"
            )
        return run_proxy(_resolve(command), session_name=args.name)

    if args.cmd == "tail":
        path = Path(args.path) if args.path else latest_session(SESSIONS_DIR)
        if path is None:
            parser.error(f"no session logs found in {SESSIONS_DIR} -- run `greenlight run -- ...` first")
        if not path.exists():
            parser.error(f"no such file: {path}")
        print_banner(Console())
        tail_file(path, follow=args.follow)
        return 0

    if args.cmd == "stats":
        path = Path(args.path) if args.path else latest_session(SESSIONS_DIR)
        if path is None:
            parser.error(f"no session logs found in {SESSIONS_DIR} -- run `greenlight run -- ...` first")
        if not path.exists():
            parser.error(f"no such file: {path}")
        stats = compute_stats(path)
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(format_stats(stats, path))
        return 1 if stats["failed"] else 0

    if args.cmd == "wrap":
        from greenlight.wrap import find_configs, format_suggestions, load_servers

        paths = [Path(args.path)] if args.path else find_configs()
        if not paths:
            print("greenlight: no MCP client config found in the usual locations.", file=sys.stderr)
            print("Pass one directly: greenlight wrap path/to/config.json", file=sys.stderr)
            return 1

        print("greenlight: read-only -- nothing on disk is changed. "
              "Copy in whichever suggestions you want.\n")
        exit_code = 0
        for path in paths:
            try:
                servers = load_servers(path)
            except ValueError as e:
                print(f"greenlight: {e}", file=sys.stderr)
                exit_code = 1
                continue
            print(format_suggestions(path, servers))
            print()
        return exit_code

    if args.cmd == "serve":
        try:
            from greenlight.serve import run_serve
        except ImportError:
            print("greenlight: `serve` needs the optional dependency -- install with:", file=sys.stderr)
            print("  pip install greenlight-mcp[serve]", file=sys.stderr)
            return 1
        return run_serve()

    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
