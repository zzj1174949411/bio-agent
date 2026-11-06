"""Local MCP 2.2.0 fixture used by transport integration tests only."""

import asyncio
import os
import sys

from child_process import spawn_child
from mcp.server import MCPServer

server = MCPServer("bioagent-fixture", version="1.0")


@server.tool(name="echo", description="Return the supplied text.", structured_output=True)
def echo(text: str) -> dict[str, str]:
    return {"text": text}


@server.tool(name="large_result", description="Return a bounded test payload.")
def large_result(size: int) -> str:
    return "x" * size


@server.tool(name="delay", description="Delay for cancellation and timeout tests.")
async def delay(seconds: float) -> dict[str, float]:
    await asyncio.sleep(seconds)
    return {"seconds": seconds}


@server.tool(name="error", description="Return an MCP isError result.")
def error(message: str) -> str:
    raise RuntimeError(message)


@server.tool(name="has_model_key", description="Report whether a model key leaked into the child.")
def has_model_key() -> bool:
    return "BIOAGENT_DEEPSEEK_API_KEY" in os.environ or "DEEPSEEK_API_KEY" in os.environ


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "stdio":
        server.run("stdio")
    elif mode == "stdio-child":
        child = spawn_child()
        try:
            server.run("stdio")
        finally:
            child.terminate()
            child.wait(timeout=3)
    elif mode == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    elif mode == "exit":
        raise SystemExit(0)
    else:
        raise SystemExit("unknown fixture mode")
