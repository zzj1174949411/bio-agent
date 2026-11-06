from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from bioagent.extensions.gateway import ToolGateway
from bioagent.extensions.mcp_client import McpClientAdapter
from bioagent.extensions.models import HttpConfig, McpCallResult, McpServerConfig, McpTool
from bioagent.extensions.policy import ExtensionError, ToolPolicy, arguments_hash
from bioagent.extensions.store import SkillStore
from bioagent.workbench.models import TurnStatus
from bioagent.workbench.store import WorkbenchStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mcp" / "server.py"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError("fixture HTTP server did not start")


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_local_readonly_fixture_supports_both_transports(tmp_path: Path, transport: str) -> None:
    process: subprocess.Popen[bytes] | None = None
    if transport == "stdio":
        config = McpServerConfig(
            id=uuid4(),
            label="Task33 stdio fixture",
            transport="stdio",
            stdio={
                "executable": sys.executable,
                "argv": (str(FIXTURE), "stdio"),
                "cwd": str(tmp_path),
            },
        )
    else:
        port = _free_port()
        process = subprocess.Popen(
            [sys.executable, str(FIXTURE), "http", str(port)],
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        _wait_for_port(port)
        config = McpServerConfig(
            id=uuid4(),
            label="Task33 HTTP fixture",
            transport="http",
            http=HttpConfig(endpoint=f"http://127.0.0.1:{port}/mcp"),
        )

    async def exercise() -> None:
        async with McpClientAdapter() as adapter:
            await adapter.connect(config)
            tools = await adapter.list_tools(config.id)
            result = await adapter.call_tool(config.id, "echo", {"text": transport})
            assert any(tool.name == "echo" for tool in tools)
            assert result.structured_content == {"text": transport}

    try:
        asyncio.run(exercise())
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_restart_revokes_pending_approval_and_records_unknown_outcome(tmp_path: Path) -> None:
    class FailingAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def call_tool(self, *_args: object, **_kwargs: object) -> McpCallResult:
            self.calls += 1
            raise ConnectionError("fixture connection dropped after dispatch")

    extension_db = tmp_path / "extensions.sqlite"
    workbench_db = tmp_path / "workbench.sqlite"
    store = SkillStore(extension_db)
    workbench = WorkbenchStore(workbench_db)
    project = workbench.create_project("Task33 fixture")
    conversation = workbench.create_conversation(project.id, "restart")
    turn = workbench.begin_turn(conversation.id, uuid4(), "call echo", None)
    workbench.update_turn(turn.id, TurnStatus.RUNNING)
    adapter = FailingAdapter()
    gateway = ToolGateway(store, adapter, workbench)
    server = McpServerConfig(
        id=uuid4(),
        label="fixture",
        transport="http",
        http=HttpConfig(endpoint="http://127.0.0.1:1/mcp"),
    )
    descriptor = gateway.register_tools(
        server,
        (McpTool(name="echo", input_schema={"type": "object"}),),
    )[0]
    gateway.set_policy(descriptor.qualified_name, ToolPolicy.ALLOW_READ)

    pending = gateway.request_approval(
        conversation_id=str(conversation.id),
        turn_id=str(turn.id),
        qualified_tool_name=descriptor.qualified_name,
        arguments={"text": "restart"},
    )
    store.close()
    restarted = SkillStore(extension_db)
    restarted_gateway = ToolGateway(restarted, adapter, workbench)
    assert restarted_gateway.revoke_pending_approvals() == 1
    with pytest.raises(ExtensionError, match="APPROVAL_REVOKED"):
        restarted_gateway.decide_approval(
            call_id=str(pending["call_id"]),
            approval_id=str(pending["approval_id"]),
            decision="approve",
            capability_revision_value=str(pending["capability_revision"]),
            arguments_hash_value=arguments_hash({"text": "restart"}),
        )

    with pytest.raises(ExtensionError, match="TOOL_OUTCOME_UNKNOWN"):
        asyncio.run(
            restarted_gateway.call(
                conversation_id=str(conversation.id),
                turn_id=str(turn.id),
                qualified_tool_name=descriptor.qualified_name,
                arguments={"text": "after-restart"},
            )
        )
    assert adapter.calls == 1
    events = workbench.list_events(conversation.id)
    assert any(
        event.kind == "action.failed" and event.payload.get("error_code") == "TOOL_OUTCOME_UNKNOWN"
        for event in events
    )
    restarted.close()
    workbench.close()
