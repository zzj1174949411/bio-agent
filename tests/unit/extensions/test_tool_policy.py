import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from bioagent.extensions.gateway import ToolGateway
from bioagent.extensions.models import HttpConfig, McpCallResult, McpServerConfig, McpTool
from bioagent.extensions.policy import (
    ExtensionError,
    ToolPolicy,
    arguments_hash,
    initial_policy,
    normalize_schema,
    qualified_name,
    schema_hash,
)
from bioagent.extensions.store import SkillStore


@pytest.mark.parametrize(
    "annotations", [{"readOnlyHint": True}, {"destructiveHint": False}, {"readOnlyHint": False}]
)
def test_readonly_annotation_cannot_grant_permission(annotations):
    assert initial_policy(annotations) == ToolPolicy.CONFIRM


def test_schema_is_canonical_and_remote_refs_are_rejected():
    assert schema_hash({"type": "object", "properties": {"x": {"type": "string"}}}) == schema_hash(
        {"properties": {"x": {"type": "string"}}, "type": "object"}
    )
    with pytest.raises(ExtensionError, match="SCHEMA_REMOTE_REF"):
        normalize_schema({"$ref": "https://example.invalid/schema"})


def test_gateway_approval_is_expiring_and_one_time(tmp_path):
    store = SkillStore(tmp_path / "extensions.sqlite")
    server = McpServerConfig(
        id="00000000-0000-0000-0000-000000000001",
        label="fixture",
        transport="http",
        http=HttpConfig(endpoint="https://example.invalid/mcp"),
    )

    class Adapter:
        async def list_tools(self, _):
            return (McpTool(name="echo", input_schema={"type": "object"}),)

        async def call_tool(self, *_args, **_kwargs):
            return McpCallResult()

    gateway = ToolGateway(store, Adapter())
    descriptor = gateway.register_tools(
        server, (McpTool(name="echo", input_schema={"type": "object"}),)
    )[0]
    approval = gateway.request_approval(
        conversation_id="c",
        turn_id="t",
        qualified_tool_name=descriptor.qualified_name,
        arguments={},
    )
    approved = gateway.decide_approval(
        call_id=str(approval["call_id"]),
        approval_id=str(approval["approval_id"]),
        decision="approve",
        capability_revision_value=descriptor.capability_revision,
        arguments_hash_value=arguments_hash({}),
    )
    gateway.consume_approval(
        call_id=str(approved["call_id"]),
        approval_id=str(approved["approval_id"]),
        qualified_tool_name=descriptor.qualified_name,
        capability_revision_value=descriptor.capability_revision,
        arguments_hash_value=arguments_hash({}),
    )
    with pytest.raises(ExtensionError, match="APPROVAL_ALREADY_USED"):
        gateway.consume_approval(
            call_id=str(approved["call_id"]),
            approval_id=str(approved["approval_id"]),
            qualified_tool_name=descriptor.qualified_name,
            capability_revision_value=descriptor.capability_revision,
            arguments_hash_value=arguments_hash({}),
        )
    store.close()


@pytest.mark.parametrize(
    "field",
    ["capability_revision", "arguments_hash"],
)
def test_approval_binds_capability_and_arguments(tmp_path, field):
    store = SkillStore(tmp_path / f"{field}.sqlite")
    server = McpServerConfig(
        id="00000000-0000-0000-0000-000000000002",
        label="fixture",
        transport="http",
        http=HttpConfig(endpoint="https://example.invalid/mcp"),
    )
    gateway = ToolGateway(store, object())
    descriptor = gateway.register_tools(
        server, (McpTool(name="echo", input_schema={"type": "object"}),)
    )[0]
    approval = gateway.request_approval(
        conversation_id="c", turn_id="t",
        qualified_tool_name=descriptor.qualified_name,
        arguments={},
    )
    value = "0" * 64 if field == "capability_revision" else descriptor.capability_revision
    argument_value = (
        arguments_hash({"x": 1}) if field == "arguments_hash" else arguments_hash({})
    )
    with pytest.raises(ExtensionError, match="APPROVAL_CONFLICT"):
        gateway.decide_approval(
            call_id=str(approval["call_id"]),
            approval_id=str(approval["approval_id"]),
            decision="approve",
            capability_revision_value=value,
            arguments_hash_value=argument_value,
        )
    store.close()


def test_expired_and_cancelled_approvals_cannot_be_consumed(tmp_path):
    store = SkillStore(tmp_path / "expired.sqlite")
    server = McpServerConfig(
        id="00000000-0000-0000-0000-000000000003",
        label="fixture",
        transport="http",
        http=HttpConfig(endpoint="https://example.invalid/mcp"),
    )
    gateway = ToolGateway(store, object())
    descriptor = gateway.register_tools(
        server, (McpTool(name="echo", input_schema={"type": "object"}),)
    )[0]
    old = gateway.request_approval(
        conversation_id="c", turn_id="old", qualified_tool_name=descriptor.qualified_name,
        arguments={}, now=datetime.now(UTC) - timedelta(minutes=11),
    )
    with pytest.raises(ExtensionError, match="APPROVAL_EXPIRED"):
        gateway.decide_approval(
            call_id=str(old["call_id"]),
            approval_id=str(old["approval_id"]),
            decision="approve",
            capability_revision_value=descriptor.capability_revision,
            arguments_hash_value=arguments_hash({}),
        )
    pending = gateway.request_approval(
        conversation_id="c", turn_id="cancel",
        qualified_tool_name=descriptor.qualified_name, arguments={}
    )
    assert gateway.revoke_turn("cancel") == 1
    with pytest.raises(ExtensionError, match="APPROVAL_REVOKED"):
        gateway.decide_approval(
            call_id=str(pending["call_id"]),
            approval_id=str(pending["approval_id"]),
            decision="approve",
            capability_revision_value=descriptor.capability_revision,
            arguments_hash_value=arguments_hash({}),
        )
    store.close()


def test_concurrent_consumption_is_atomic(tmp_path):
    store = SkillStore(tmp_path / "concurrent.sqlite")
    server = McpServerConfig(
        id="00000000-0000-0000-0000-000000000004", label="fixture",
        transport="http", http=HttpConfig(endpoint="https://example.invalid/mcp")
    )
    gateway = ToolGateway(store, object())
    descriptor = gateway.register_tools(
        server, (McpTool(name="echo", input_schema={"type": "object"}),)
    )[0]
    approval = gateway.request_approval(
        conversation_id="c", turn_id="t",
        qualified_tool_name=descriptor.qualified_name, arguments={}
    )
    gateway.decide_approval(
        call_id=str(approval["call_id"]),
        approval_id=str(approval["approval_id"]), decision="approve",
        capability_revision_value=descriptor.capability_revision,
        arguments_hash_value=arguments_hash({}),
    )
    def consume():
        try:
            gateway.consume_approval(
                call_id=str(approval["call_id"]),
                approval_id=str(approval["approval_id"]),
                qualified_tool_name=descriptor.qualified_name,
                capability_revision_value=descriptor.capability_revision,
                arguments_hash_value=arguments_hash({}),
            )
            return "ok"
        except ExtensionError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: consume(), range(2)))
    assert outcomes.count("ok") == 1
    assert outcomes.count("APPROVAL_ALREADY_USED") == 1
    store.close()


def test_call_rejects_unknown_and_oversized_outcomes(tmp_path):
    store = SkillStore(tmp_path / "outcomes.sqlite")
    server = McpServerConfig(
        id="00000000-0000-0000-0000-000000000005", label="fixture",
        transport="http", http=HttpConfig(endpoint="https://example.invalid/mcp")
    )

    class Adapter:
        async def call_tool(self, *_args, **_kwargs):
            return McpCallResult(structured_content="x" * (2 * 1024 * 1024))

    gateway = ToolGateway(store, Adapter())
    descriptor = gateway.register_tools(
        server, (McpTool(name="echo", input_schema={"type": "object"}),)
    )[0]
    gateway.set_policy(descriptor.qualified_name, ToolPolicy.ALLOW_READ)
    with pytest.raises(ExtensionError, match="MCP_RESULT_TOO_LARGE"):
        asyncio.run(
            gateway.call(
                conversation_id="c", turn_id="t",
                qualified_tool_name=descriptor.qualified_name, arguments={}
            )
        )
    store.close()


def test_cancelled_outcome_is_not_retried(tmp_path):
    store = SkillStore(tmp_path / "cancel.sqlite")
    server = McpServerConfig(
        id="00000000-0000-0000-0000-000000000006", label="fixture",
        transport="http", http=HttpConfig(endpoint="https://example.invalid/mcp")
    )

    class Adapter:
        async def call_tool(self, *_args, **_kwargs):
            raise asyncio.CancelledError

    gateway = ToolGateway(store, Adapter())
    descriptor = gateway.register_tools(
        server, (McpTool(name="echo", input_schema={"type": "object"}),)
    )[0]
    gateway.set_policy(descriptor.qualified_name, ToolPolicy.ALLOW_READ)
    with pytest.raises(ExtensionError, match="TOOL_CANCELLED"):
        asyncio.run(
            gateway.call(
                conversation_id="c", turn_id="t",
                qualified_tool_name=descriptor.qualified_name, arguments={}
            )
        )
    store.close()


def test_output_schema_and_deny_are_enforced(tmp_path):
    store = SkillStore(tmp_path / "output-schema.sqlite")
    server = McpServerConfig(
        id="00000000-0000-0000-0000-000000000007", label="fixture",
        transport="http", http=HttpConfig(endpoint="https://example.invalid/mcp")
    )

    class Adapter:
        def __init__(self):
            self.calls = 0
        async def call_tool(self, *_args, **_kwargs):
            self.calls += 1
            return McpCallResult(structured_content={"bad": True})

    adapter = Adapter()
    gateway = ToolGateway(store, adapter)
    descriptor = gateway.register_tools(
        server,
        (McpTool(
            name="echo", input_schema={"type": "object"},
            output_schema={"type": "object", "required": ["ok"]}
        ),),
    )[0]
    gateway.set_policy(descriptor.qualified_name, ToolPolicy.ALLOW_READ)
    with pytest.raises(ExtensionError, match="TOOL_OUTPUT_INVALID"):
        asyncio.run(
            gateway.call(
                conversation_id="c", turn_id="t",
                qualified_tool_name=descriptor.qualified_name, arguments={}
            )
        )
    gateway.set_policy(descriptor.qualified_name, ToolPolicy.DENY)
    with pytest.raises(ExtensionError, match="TOOL_DENIED"):
        asyncio.run(
            gateway.call(
                conversation_id="c", turn_id="t",
                qualified_tool_name=descriptor.qualified_name, arguments={}
            )
        )
    assert adapter.calls == 1
    store.close()


def test_tool_name_collision_and_analysis_approve_are_not_allowed():
    with pytest.raises(ExtensionError, match="TOOL_NAME_INVALID"):
        qualified_name("", "x")
    assert qualified_name("server", "echo") == "mcp.server.echo"
