"""
A deliberately broken stdio MCP server, hand-rolled rather than built on
the SDK because the SDK won't let you make most of these mistakes:

    - prints a log line to stdout (the classic stdio-transport bug)
    - lists a tool with no inputSchema, one with a non-object schema, one
      with no description, one with a dotted name, and a duplicate name
    - never answers tools/call
"""
import json
import sys

print("server starting up...", flush=True)  # the bug: should be stderr

TOOLS = [
    {"name": "ok_tool", "description": "Fine.", "inputSchema": {"type": "object"}},
    {"name": "no_schema", "description": "Missing inputSchema."},
    {"name": "array_schema", "description": "Wrong type.", "inputSchema": {"type": "array"}},
    {"name": "no_description", "inputSchema": {"type": "object"}},
    {"name": "files.read", "description": "Dotted name.", "inputSchema": {"type": "object"}},
    {"name": "ok_tool", "description": "Duplicate.", "inputSchema": {"type": "object"}},
]

for line in sys.stdin:
    msg = json.loads(line)
    method, msg_id = msg.get("method"), msg.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "bad", "version": "0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    else:
        continue  # notifications, and tools/call -- which never gets an answer
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()
