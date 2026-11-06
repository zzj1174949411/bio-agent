import asyncio

import httpx2
import pytest

from bioagent.extensions.mcp_client import (
    McpClientAdapter,
    McpClientError,
    _guard_http_response,
    validate_http_endpoint,
)
from bioagent.extensions.models import HttpConfig, McpServerConfig, StdioConfig


def test_plain_http_is_local_only():
    assert validate_http_endpoint("http://127.0.0.1:8765/mcp") == "http://127.0.0.1:8765/mcp"
    with pytest.raises(ValueError, match="MCP_ENDPOINT_INVALID"):
        validate_http_endpoint("http://remote.example/mcp")


@pytest.mark.parametrize(
    "endpoint, valid",
    [
        ("http://localhost:8765/mcp?view=1", True),
        ("http://[::1]:8765/mcp", True),
        ("https://remote.example/mcp?view=1", True),
        ("http://remote.example/mcp", False),
        ("https://user:password@remote.example/mcp", False),
        ("https://remote.example/mcp#fragment", False),
        ("https://remote.example/mcp#", False),
        ("https://remote.example/mcp?token=secret", False),
        ("https://remote.example/mcp?token", False),
    ],
)
def test_http_endpoint_security_boundaries(endpoint, valid):
    if valid:
        assert validate_http_endpoint(endpoint) == endpoint
    else:
        with pytest.raises(ValueError, match="MCP_ENDPOINT_INVALID"):
            validate_http_endpoint(endpoint)


def stdio_config(tmp_path, index=1):
    executable = tmp_path / f"server-{index}.exe"
    executable.write_text("fixture", encoding="utf-8")
    return McpServerConfig(
        id=f"00000000-0000-0000-0000-{index:012d}",
        label=f"fixture-{index}",
        transport="stdio",
        stdio=StdioConfig(
            executable=str(executable),
            argv=("--fixture",),
            cwd=str(tmp_path),
            env_refs={"MCP_FIXTURE": "secret:fixture"},
        ),
    )


class FakeSession:
    def __init__(self):
        self.entered = False
        self.closed = False
        self.calls = []

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def list_tools(self):
        return {
            "tools": [
                {"name": "echo", "description": "echo", "inputSchema": {"type": "object"}}
            ]
        }

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"structured_content": {"echo": arguments}, "content": [], "is_error": False}


def test_adapter_lifecycle_uses_fake_session_and_disconnects():
    sessions = []

    def factory(_config):
        session = FakeSession()
        sessions.append(session)
        return session

    config = McpServerConfig(
        id="00000000-0000-0000-0000-000000000001",
        label="fake",
        transport="http",
        http=HttpConfig(endpoint="https://remote.example/mcp"),
    )
    async def exercise():
        async with McpClientAdapter(session_factory=factory) as adapter:
            connection = await adapter.connect(config)
            assert connection.server_id == config.id
            assert connection.configured is True
            tools = await adapter.list_tools(config.id)
            assert tools[0].name == "echo"
            assert tools[0].input_schema == {"type": "object"}
            result = await adapter.call_tool(config.id, "echo", {"text": "hello"})
            assert result.structured_content == {"echo": {"text": "hello"}}
            await adapter.disconnect(config.id)

    asyncio.run(exercise())
    assert sessions[0].entered is True
    assert sessions[0].closed is True


def test_adapter_rejects_duplicate_and_ninth_connection(tmp_path):
    sessions = []

    def factory(_config):
        session = FakeSession()
        sessions.append(session)
        return session

    async def exercise():
        async with McpClientAdapter(session_factory=factory) as adapter:
            configs = [
                McpServerConfig(
                    id=f"00000000-0000-0000-0000-{index:012d}",
                    label=f"fake-{index}",
                    transport="http",
                    http=HttpConfig(endpoint=f"https://remote.example/{index}"),
                )
                for index in range(1, 10)
            ]
            for config in configs[:8]:
                await adapter.connect(config)
            with pytest.raises(McpClientError, match="MCP_CONNECTION_LIMIT"):
                await adapter.connect(configs[8])
            with pytest.raises(McpClientError, match="MCP_ALREADY_CONNECTED"):
                await adapter.connect(configs[0])

    asyncio.run(exercise())


def test_adapter_timeout_is_deterministic(tmp_path):
    class SlowSession(FakeSession):
        async def call_tool(self, _name, _arguments):
            await __import__("asyncio").sleep(0.05)
            return {"structured_content": {"ok": True}, "content": [], "is_error": False}

    config = stdio_config(tmp_path)

    async def exercise():
        async with McpClientAdapter(session_factory=lambda _config: SlowSession()) as adapter:
            await adapter.connect(config)
            with pytest.raises(McpClientError, match="MCP_CALL_TIMEOUT"):
                await adapter.call_tool(config.id, "slow", {}, timeout=0.001)

    asyncio.run(exercise())


def test_adapter_cancellation_has_stable_error(tmp_path):
    class CancellableSession(FakeSession):
        async def call_tool(self, _name, _arguments):
            await asyncio.sleep(10)
            return {"content": [], "is_error": False}

    config = stdio_config(tmp_path)

    async def exercise():
        async with McpClientAdapter(
            session_factory=lambda _config: CancellableSession()
        ) as adapter:
            await adapter.connect(config)
            task = asyncio.create_task(adapter.call_tool(config.id, "slow", {}))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(McpClientError, match="MCP_CALL_CANCELLED"):
                await task

    asyncio.run(exercise())


def test_stdio_configuration_requires_absolute_command_and_cwd(tmp_path):
    with pytest.raises(ValueError):
        StdioConfig(executable="relative-server", argv=(), cwd=str(tmp_path))
    with pytest.raises(ValueError):
        StdioConfig(executable=str(tmp_path / "server"), argv=(), cwd="relative")


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_http_response_guard_rejects_redirects_and_oversize_before_decode(status):
    response = httpx2.Response(status, headers={"content-length": str(2 * 1024 * 1024 + 1)})

    async def exercise():
        with pytest.raises(McpClientError, match="MCP_REDIRECT_REJECTED"):
            await _guard_http_response(response)

    asyncio.run(exercise())

    response = httpx2.Response(200, headers={"content-length": str(2 * 1024 * 1024 + 1)})
    with pytest.raises(McpClientError, match="MCP_RESULT_TOO_LARGE"):
        asyncio.run(_guard_http_response(response))
