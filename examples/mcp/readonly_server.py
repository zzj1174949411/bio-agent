"""Synthetic read-only MCP echo server for local Bio-Agent demonstrations.

Run it only as an explicitly configured local fixture. It never reads files,
starts child processes, or returns statistical evidence.
"""

from __future__ import annotations

import sys

from mcp.server import MCPServer

server = MCPServer("bioagent-readonly-fixture", version="2.2.0")


@server.tool(
    name="echo",
    description="Return the supplied text without changing local state.",
    structured_output=True,
)
def echo(text: str) -> dict[str, str]:
    """Echo synthetic input; this output is not scientific evidence."""

    return {"text": text}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"stdio", "http"}:
        raise SystemExit("usage: readonly_server.py stdio | http [port]")
    if sys.argv[1] == "stdio":
        server.run("stdio")
    else:
        if len(sys.argv) != 3:
            raise SystemExit("usage: readonly_server.py http PORT")
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
