import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bioagent.extensions.mcp_client import McpClientAdapter, McpClientError
from bioagent.extensions.models import HttpConfig, McpServerConfig, StdioConfig

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mcp" / "server.py"


def wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError("fixture HTTP server did not start")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_real_sdk_stdio_fixture_round_trip(tmp_path):
    config = McpServerConfig(
        id="00000000-0000-0000-0000-000000000101",
        label="stdio fixture",
        transport="stdio",
        stdio=StdioConfig(
            executable=sys.executable,
            argv=(str(FIXTURE), "stdio"),
            cwd=str(tmp_path),
        ),
    )

    async def exercise():
        async with McpClientAdapter() as adapter:
            await adapter.connect(config)
            tools = await adapter.list_tools(config.id)
            result = await adapter.call_tool(config.id, "echo", {"text": "stdio"})
            delayed = await adapter.call_tool(config.id, "delay", {"seconds": 0.01})
            failed = await adapter.call_tool(config.id, "error", {"message": "fixture"})
            assert any(tool.name == "echo" for tool in tools)
            assert result.structured_content == {"text": "stdio"}
            assert delayed.structured_content == {"seconds": 0.01}
            assert failed.is_error is True

    asyncio.run(exercise())


def test_real_sdk_http_fixture_round_trip(tmp_path):
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, str(FIXTURE), "http", str(port)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    try:
        wait_for_port(port)
        config = McpServerConfig(
            id="00000000-0000-0000-0000-000000000102",
            label="http fixture",
            transport="http",
            http=HttpConfig(endpoint=f"http://127.0.0.1:{port}/mcp"),
        )

        async def exercise():
            async with McpClientAdapter() as adapter:
                await adapter.connect(config)
                result = await adapter.call_tool(config.id, "echo", {"text": "http"})
                assert result.structured_content == {"text": "http"}

        asyncio.run(exercise())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_stdio_frame_limit_and_model_key_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOAGENT_DEEPSEEK_API_KEY", "model-key-must-not-cross-boundary")
    config = McpServerConfig(
        id="00000000-0000-0000-0000-000000000103",
        label="stdio limits",
        transport="stdio",
        stdio=StdioConfig(
            executable=sys.executable,
            argv=(str(FIXTURE), "stdio"),
            cwd=str(tmp_path),
        ),
    )

    async def exercise():
        async with McpClientAdapter() as adapter:
            await adapter.connect(config)
            result = await adapter.call_tool(config.id, "has_model_key", {})
            assert result.structured_content == {"result": False}
            with pytest.raises(McpClientError, match="MCP_CALL_FAILED|MCP_STDIO_FRAME_TOO_LARGE"):
                await adapter.call_tool(config.id, "large_result", {"size": 2 * 1024 * 1024})

    asyncio.run(exercise())


def test_http_body_limit_rejects_oversized_result(tmp_path):
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, str(FIXTURE), "http", str(port)],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    try:
        wait_for_port(port)
        config = McpServerConfig(
            id="00000000-0000-0000-0000-000000000104",
            label="http limit",
            transport="http",
            http=HttpConfig(endpoint=f"http://127.0.0.1:{port}/mcp"),
        )

        async def exercise():
            async with McpClientAdapter() as adapter:
                await adapter.connect(config)
                with pytest.raises(
                    McpClientError,
                    match="MCP_CALL_FAILED|MCP_RESULT_TOO_LARGE|MCP_CALL_CANCELLED",
                ):
                    await adapter.call_tool(
                        config.id, "large_result", {"size": 2 * 1024 * 1024}
                    )

        asyncio.run(exercise())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_stdio_disconnect_cleans_adapter_owned_child_process(tmp_path):
    config = McpServerConfig(
        id="00000000-0000-0000-0000-000000000105",
        label="stdio child fixture",
        transport="stdio",
        stdio=StdioConfig(
            executable=sys.executable,
            argv=(str(FIXTURE), "stdio-child"),
            cwd=str(tmp_path),
        ),
    )

    async def exercise():
        async with McpClientAdapter() as adapter:
            await adapter.connect(config)
            deadline = time.monotonic() + 5
            while not (tmp_path / "child.pid").exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert (tmp_path / "child.pid").exists()
            child_pid = int((tmp_path / "child.pid").read_text(encoding="ascii"))
        for _ in range(20):
            try:
                os.kill(child_pid, 0)
            except OSError:
                return
            await asyncio.sleep(0.05)
        raise AssertionError("adapter-owned child process survived disconnect")

    asyncio.run(exercise())
