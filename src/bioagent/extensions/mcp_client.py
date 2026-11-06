"""MCP 2.2.0 adapter with bounded local stdio and Streamable HTTP transports."""

from __future__ import annotations

import asyncio
import math
import os
import signal
import subprocess
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, cast
from urllib.parse import parse_qsl, urlsplit

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage
from mcp.types import jsonrpc_message_adapter

from bioagent.extensions.models import (
    HttpConfig,
    McpCallResult,
    McpConnection,
    McpServerConfig,
    McpTool,
    StdioConfig,
)

MAX_CONNECTIONS = 8
CONNECT_TIMEOUT_SECONDS = 10.0
DISCOVERY_TIMEOUT_SECONDS = 10.0
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0
MAX_CALL_TIMEOUT_SECONDS = 300.0
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
_LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SENSITIVE_QUERY_KEYS = {
    "token",
    "access_token",
    "api_key",
    "apikey",
    "key",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "x_api_key",
    "api-key",
    "x-api-key",
}
_INHERITED_ENV = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")


class McpClientError(RuntimeError):
    """Stable adapter error code; details never include secret values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_http_endpoint(value: str) -> str:
    """Allow local cleartext and remote HTTPS without userinfo or credential query."""
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ValueError("MCP_ENDPOINT_INVALID") from exc
    local = hostname in _LOCAL_HTTP_HOSTS
    if (
        not hostname
        or parts.scheme not in {"http", "https"}
        or (parts.scheme == "http" and not local)
        or parts.username is not None
        or parts.password is not None
        or "#" in value
        or any(
            key.casefold().replace("-", "_") in _SENSITIVE_QUERY_KEYS
            for key, _ in parse_qsl(parts.query, keep_blank_values=True)
        )
        or port == 0
    ):
        raise ValueError("MCP_ENDPOINT_INVALID")
    return value


def _value(item: object, *names: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        for name in names:
            if name in item:
                return item[name]
        return default
    for name in names:
        result = getattr(item, name, default)
        if result is not default:
            return result
    return default


class _Session(Protocol):
    async def list_tools(self) -> object: ...

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object: ...


class _LimitedByteStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream) -> None:
        self._stream = stream
        self._total = 0

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        async for chunk in self._stream:
            self._total += len(chunk)
            if self._total > MAX_MESSAGE_BYTES:
                raise McpClientError("MCP_RESULT_TOO_LARGE")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


async def _guard_http_response(response: httpx2.Response) -> None:
    if 300 <= response.status_code < 400:
        raise McpClientError("MCP_REDIRECT_REJECTED")
    length = response.headers.get("content-length")
    if length is not None:
        try:
            parsed_length = int(length)
            if parsed_length < 0:
                raise McpClientError("MCP_RESPONSE_INVALID")
            if parsed_length > MAX_MESSAGE_BYTES:
                raise McpClientError("MCP_RESULT_TOO_LARGE")
        except ValueError as exc:
            raise McpClientError("MCP_RESPONSE_INVALID") from exc
    if not isinstance(response.stream, httpx2.AsyncByteStream):
        raise McpClientError("MCP_RESPONSE_INVALID")
    response.stream = _LimitedByteStream(response.stream)


class _BoundedStdioTransport:
    """A public-SDK-compatible transport that bounds each newline-delimited frame."""

    def __init__(self, config: StdioConfig, env: dict[str, str]) -> None:
        self._config = config
        self._env = env
        self._stack = AsyncExitStack()
        self._process: anyio.abc.Process | None = None
        self._read_send: anyio.abc.ObjectSendStream[object] | None = None
        self._write_receive: anyio.abc.ObjectReceiveStream[object] | None = None

    async def __aenter__(self) -> tuple[object, object]:
        try:
            return await self._enter()
        except BaseException:
            if self._process is not None:
                with anyio.CancelScope(shield=True):
                    await self._stop_process(self._process)
                await self._process.aclose()
            await self._stack.aclose()
            raise

    async def _enter(self) -> tuple[object, object]:
        command = [self._config.executable, *self._config.argv]
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self._process = await anyio.open_process(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._config.cwd,
            env=self._env,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        read_send, read_receive = anyio.create_memory_object_stream[object](0)
        write_send, write_receive = anyio.create_memory_object_stream[object](0)
        self._read_send = await self._stack.enter_async_context(read_send)
        read_stream = await self._stack.enter_async_context(read_receive)
        write_stream = await self._stack.enter_async_context(write_send)
        self._write_receive = await self._stack.enter_async_context(write_receive)
        task_group = await self._stack.enter_async_context(anyio.create_task_group())
        task_group.start_soon(self._stdout_reader, read_send)
        task_group.start_soon(self._stdin_writer, write_receive)
        task_group.start_soon(self._stderr_reader)
        return read_stream, write_stream

    async def __aexit__(self, *_: object) -> None:
        if self._write_receive is not None:
            await self._write_receive.aclose()
        if self._process is not None:
            with anyio.CancelScope(shield=True):
                await self._stop_process(self._process)
        await self._stack.aclose()
        if self._process is not None:
            await self._process.aclose()

    async def _stdout_reader(self, send: anyio.abc.ObjectSendStream[object]) -> None:
        assert self._process is not None and self._process.stdout is not None
        buffer = bytearray()
        try:
            async for chunk in self._process.stdout:
                buffer.extend(chunk)
                if len(buffer) > MAX_MESSAGE_BYTES and b"\n" not in buffer:
                    await send.send(McpClientError("MCP_STDIO_FRAME_TOO_LARGE"))
                    return
                while b"\n" in buffer:
                    line, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    if len(line) > MAX_MESSAGE_BYTES:
                        await send.send(McpClientError("MCP_STDIO_FRAME_TOO_LARGE"))
                        return
                    try:
                        message = jsonrpc_message_adapter.validate_json(line, by_name=False)
                        await send.send(SessionMessage(message))
                    except Exception as exc:  # malformed server output is untrusted data
                        await send.send(exc)
                        return
            if buffer:
                await send.send(McpClientError("MCP_STDIO_FRAME_INVALID"))
        finally:
            await send.aclose()

    async def _stdin_writer(self, receive: anyio.abc.ObjectReceiveStream[object]) -> None:
        assert self._process is not None and self._process.stdin is not None
        try:
            async for item in receive:
                if not isinstance(item, SessionMessage):
                    continue
                payload = item.message.model_dump_json(by_alias=True, exclude_unset=True).encode(
                    "utf-8"
                )
                if len(payload) > MAX_MESSAGE_BYTES:
                    raise McpClientError("MCP_STDIO_FRAME_TOO_LARGE")
                await self._process.stdin.send(payload + b"\n")
        except anyio.ClosedResourceError:
            return

    async def _stderr_reader(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        async for _ in self._process.stderr:
            pass

    @staticmethod
    async def _stop_process(process: anyio.abc.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                shell=False,
                timeout=3,
            )
        else:
            try:
                killpg = getattr(os, "killpg", None)
                if killpg is None:
                    process.kill()
                else:
                    killpg(process.pid, getattr(signal, "SIGTERM", 15))
            except ProcessLookupError:
                return
        try:
            with anyio.fail_after(3):
                await process.wait()
        except TimeoutError:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    killpg = getattr(os, "killpg", None)
                    if killpg is None:
                        process.kill()
                    else:
                        killpg(process.pid, getattr(signal, "SIGKILL", 9))
                except ProcessLookupError:
                    return
            await process.wait()


class _HttpSession:
    def __init__(self, config: HttpConfig, headers: dict[str, str]) -> None:
        self._config = config
        self._headers = headers
        self._http: httpx2.AsyncClient | None = None
        self._client: Client | None = None

    async def __aenter__(self) -> object:
        timeout = httpx2.Timeout(
            DEFAULT_CALL_TIMEOUT_SECONDS,
            connect=CONNECT_TIMEOUT_SECONDS,
            read=MAX_CALL_TIMEOUT_SECONDS,
        )
        self._http = httpx2.AsyncClient(
            headers=self._headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"response": [_guard_http_response]},
        )
        await self._http.__aenter__()
        transport = streamable_http_client(
            validate_http_endpoint(self._config.endpoint), http_client=self._http
        )
        self._client = Client(transport, read_timeout_seconds=DISCOVERY_TIMEOUT_SECONDS)
        try:
            return await self._client.__aenter__()
        except BaseException:
            await self._http.__aexit__(None, None, None)
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._client is not None:
                await self._client.__aexit__(exc_type, exc, tb)
        except BaseException:
            # A bounded-response guard can fail a background SDK task; cleanup
            # must still close the HTTP client without masking that call error.
            pass
        finally:
            if self._http is not None:
                await self._http.__aexit__(exc_type, exc, tb)


class _ClientSession:
    """Enter the released SDK Client around a custom bounded transport."""

    def __init__(self, transport: AbstractAsyncContextManager[object]) -> None:
        self._client = Client(cast(Any, transport), read_timeout_seconds=DISCOVERY_TIMEOUT_SECONDS)

    async def __aenter__(self) -> object:
        return await self._client.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc, tb)


@dataclass
class _ConnectionState:
    config: McpServerConfig
    context: AbstractAsyncContextManager[object]
    session: _Session


SessionFactory = Callable[[McpServerConfig], AbstractAsyncContextManager[object]]
SecretResolver = Callable[[str], str | None]


class McpClientAdapter:
    """Stable async adapter; all mcp SDK imports and types remain in this module."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self._session_factory = session_factory or self._build_session
        self._secret_resolver = secret_resolver
        self._connections: dict[str, _ConnectionState] = {}

    async def __aenter__(self) -> McpClientAdapter:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self, config: McpServerConfig) -> McpConnection:
        identity = str(config.id)
        if not config.enabled:
            raise McpClientError("MCP_SERVER_DISABLED")
        if identity in self._connections:
            raise McpClientError("MCP_ALREADY_CONNECTED")
        if len(self._connections) >= MAX_CONNECTIONS:
            raise McpClientError("MCP_CONNECTION_LIMIT")
        context: AbstractAsyncContextManager[object] | None = None
        entered = False
        try:
            context = self._session_factory(config)
            session = cast(
                _Session,
                await asyncio.wait_for(context.__aenter__(), CONNECT_TIMEOUT_SECONDS),
            )
            entered = True
            self._connections[identity] = _ConnectionState(config, context, session)
            protocol = getattr(session, "protocol_version", None)
            return McpConnection(
                server_id=config.id, revision=config.revision, protocol_version=protocol
            )
        except TimeoutError as exc:
            if entered and context is not None:
                await context.__aexit__(None, None, None)
            raise McpClientError("MCP_CONNECT_TIMEOUT") from exc
        except McpClientError:
            if entered and context is not None:
                await context.__aexit__(None, None, None)
            raise
        except ValueError as exc:
            if entered and context is not None:
                await context.__aexit__(None, None, None)
            code = (
                exc.args[0] if exc.args and isinstance(exc.args[0], str) else "MCP_CONNECT_FAILED"
            )
            if not code.startswith("MCP_"):
                code = "MCP_CONNECT_FAILED"
            raise McpClientError(code) from exc
        except Exception as exc:
            if entered and context is not None:
                await context.__aexit__(None, None, None)
            raise McpClientError("MCP_CONNECT_FAILED") from exc

    async def list_tools(self, server_id: str) -> tuple[McpTool, ...]:
        connection = self._connection(server_id)
        try:
            response = await asyncio.wait_for(
                connection.session.list_tools(), DISCOVERY_TIMEOUT_SECONDS
            )
            raw_tools = _value(response, "tools", default=[])
            if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, (str, bytes)):
                raise ValueError
            return tuple(self._tool(item) for item in raw_tools)
        except TimeoutError as exc:
            raise McpClientError("MCP_DISCOVERY_TIMEOUT") from exc
        except McpClientError:
            raise
        except Exception as exc:
            raise McpClientError("MCP_DISCOVERY_FAILED") from exc

    async def call_tool(
        self,
        server_id: str,
        name: str,
        arguments: dict[str, object],
        timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
        *,
        turn_remaining_seconds: float | None = None,
    ) -> McpCallResult:
        connection = self._connection(server_id)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
            or timeout > MAX_CALL_TIMEOUT_SECONDS
        ):
            raise McpClientError("MCP_CALL_TIMEOUT_INVALID")
        effective = timeout
        if turn_remaining_seconds is not None:
            if (
                isinstance(turn_remaining_seconds, bool)
                or not isinstance(turn_remaining_seconds, (int, float))
                or not math.isfinite(turn_remaining_seconds)
            ):
                raise McpClientError("MCP_CALL_TIMEOUT_INVALID")
            effective = min(effective, turn_remaining_seconds)
        if effective <= 0:
            raise McpClientError("MCP_CALL_TIMEOUT")
        try:
            raw = await asyncio.wait_for(connection.session.call_tool(name, arguments), effective)
            result = self._result(raw)
            if len(result.model_dump_json().encode("utf-8")) > MAX_MESSAGE_BYTES:
                raise McpClientError("MCP_RESULT_TOO_LARGE")
            return result
        except TimeoutError as exc:
            raise McpClientError("MCP_CALL_TIMEOUT") from exc
        except asyncio.CancelledError as exc:
            raise McpClientError("MCP_CALL_CANCELLED") from exc
        except McpClientError:
            raise
        except Exception as exc:
            raise McpClientError("MCP_CALL_FAILED") from exc

    async def disconnect(self, server_id: str) -> None:
        identity = str(server_id)
        connection = self._connections.pop(identity, None)
        if connection is None:
            return
        try:
            await connection.context.__aexit__(None, None, None)
        except Exception as exc:
            raise McpClientError("MCP_DISCONNECT_FAILED") from exc

    async def close(self) -> None:
        errors: list[BaseException] = []
        for identity in tuple(self._connections):
            try:
                await self.disconnect(identity)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise McpClientError("MCP_CLOSE_FAILED") from errors[0]

    def _connection(self, server_id: str) -> _ConnectionState:
        connection = self._connections.get(str(server_id))
        if connection is None:
            raise McpClientError("MCP_NOT_CONNECTED")
        return connection

    @staticmethod
    def _tool(item: object) -> McpTool:
        name = _value(item, "name", default="")
        description = _value(item, "description", default="")
        if not isinstance(name, str):
            raise ValueError
        if description is None:
            description = ""
        if not isinstance(description, str):
            raise ValueError
        schema = _value(item, "input_schema", "inputSchema", default={})
        output_schema = _value(item, "output_schema", "outputSchema", default=None)
        annotations = _value(item, "annotations", default={})
        if annotations is None:
            annotations = {}
        if (
            not isinstance(schema, Mapping)
            or (output_schema is not None and not isinstance(output_schema, Mapping))
            or not isinstance(annotations, Mapping)
        ):
            raise ValueError
        return McpTool(
            name=name,
            description=description,
            input_schema=dict(schema),
            output_schema=dict(output_schema) if isinstance(output_schema, Mapping) else None,
            annotations=dict(annotations),
        )

    @staticmethod
    def _result(raw: object) -> McpCallResult:
        content = _value(raw, "content", default=[])
        if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
            raise ValueError
        structured = _value(raw, "structured_content", "structuredContent", default=None)
        error = _value(raw, "is_error", "isError", default=False)
        return McpCallResult(
            content=tuple(content), structured_content=structured, is_error=bool(error)
        )

    def _build_session(self, config: McpServerConfig) -> AbstractAsyncContextManager[object]:
        if config.transport == "stdio":
            assert config.stdio is not None
            transport = _BoundedStdioTransport(
                config.stdio, self._resolve_refs(config.stdio.env_refs)
            )
            return _ClientSession(transport)
        assert config.http is not None
        validate_http_endpoint(config.http.endpoint)
        return _HttpSession(config.http, self._resolve_refs(config.http.header_refs))

    def _resolve_refs(self, refs: Mapping[str, str]) -> dict[str, str]:
        resolved: dict[str, str] = {
            key: os.environ[key] for key in _INHERITED_ENV if key in os.environ
        }
        for key, reference in refs.items():
            if self._secret_resolver is None:
                raise McpClientError("MCP_SECRET_UNAVAILABLE")
            value = self._secret_resolver(reference)
            if value is None:
                raise McpClientError("MCP_SECRET_UNAVAILABLE")
            resolved[key] = value
        return resolved


@asynccontextmanager
async def open_mcp_session(
    config: McpServerConfig,
    *,
    secret_resolver: SecretResolver | None = None,
) -> AsyncIterator[object]:
    """Internal helper useful for embedding the adapter in an application."""
    adapter = McpClientAdapter(secret_resolver=secret_resolver)
    context = adapter._build_session(config)
    async with context as session:
        yield session
