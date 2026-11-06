"""Single enforcement point for MCP tool policy, approvals, schemas and calls."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from bioagent.extensions.mcp_client import MAX_MESSAGE_BYTES, McpClientAdapter, McpClientError
from bioagent.extensions.models import McpCallResult, McpServerConfig, McpTool
from bioagent.extensions.policy import (
    ExtensionError,
    ToolDescriptor,
    ToolPolicy,
    arguments_hash,
    capability_revision,
    initial_policy,
    qualified_name,
    schema_hash,
    validate_instance,
)
from bioagent.extensions.store import SkillStore
from bioagent.workbench.store import WorkbenchStore


class ApprovalRequired(ExtensionError):
    def __init__(self, approval: Mapping[str, object]) -> None:
        self.approval = dict(approval)
        super().__init__("APPROVAL_REQUIRED")


class ToolGateway:
    """Policy and approval enforcement; transport clients remain protocol adapters."""

    def __init__(
        self,
        store: SkillStore,
        mcp_client: McpClientAdapter,
        workbench: WorkbenchStore | None = None,
    ) -> None:
        self.store = store
        self.mcp_client = mcp_client
        self.workbench = workbench

    def list_tools(self) -> tuple[ToolDescriptor, ...]:
        return self.store.list_tools()

    def available_tools(self) -> tuple[ToolDescriptor, ...]:
        """Return the current capability snapshot visible to a model."""

        return tuple(tool for tool in self.list_tools() if tool.policy is not ToolPolicy.DENY)

    def get_tool(self, name: str) -> ToolDescriptor:
        if name == "analysis.approve":
            raise ExtensionError("TOOL_NOT_FOUND")
        return self.store.get_tool(name)

    def set_policy(
        self, name: str, policy: ToolPolicy, *, expected_capability_revision: str | None = None
    ) -> ToolDescriptor:
        descriptor = self.get_tool(name)
        if (
            expected_capability_revision is not None
            and descriptor.capability_revision != expected_capability_revision
        ):
            raise ExtensionError("CAPABILITY_REVISION_CONFLICT")
        updated_cap = capability_revision(
            descriptor.schema_hash, descriptor.connection_revision, policy
        )
        updated = descriptor.model_copy(
            update={"policy": policy, "capability_revision": updated_cap}
        )
        return self.store.update_tool(updated)

    def register_tools(
        self, server: McpServerConfig, tools: Sequence[McpTool]
    ) -> tuple[ToolDescriptor, ...]:
        registered: list[ToolDescriptor] = []
        for tool in tools:
            qname = qualified_name(str(server.id), tool.name)
            if qname == "analysis.approve" or qname.startswith("analysis."):
                raise ExtensionError("TOOL_NAME_COLLISION")
            combined_schema: dict[str, object] = {"input": tool.input_schema}
            if tool.output_schema is not None:
                combined_schema["output"] = tool.output_schema
            digest = schema_hash(combined_schema)
            old: ToolDescriptor | None
            try:
                old = self.store.get_tool(qname)
            except ExtensionError:
                old = None
            policy = (
                old.policy
                if old is not None and old.schema_hash == digest and old.server_id == str(server.id)
                else initial_policy(tool.annotations)
            )
            cap = capability_revision(digest, server.revision, policy)
            descriptor = ToolDescriptor(
                qualified_name=qname,
                server_id=str(server.id),
                tool_name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
                annotations=tool.annotations,
                schema_hash=digest,
                policy=policy,
                connection_revision=server.revision,
                capability_revision=cap,
            )
            if old is not None and old.server_id != descriptor.server_id:
                raise ExtensionError("TOOL_NAME_COLLISION")
            self.store.save_tool(descriptor)
            registered.append(descriptor)
        return tuple(registered)

    async def refresh_server_tools(self, server: McpServerConfig) -> tuple[ToolDescriptor, ...]:
        tools = await self.mcp_client.list_tools(str(server.id))
        return self.register_tools(server, tools)

    def request_approval(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        qualified_tool_name: str,
        arguments: Mapping[str, object],
        call_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        descriptor = self.get_tool(qualified_tool_name)
        if descriptor.policy is ToolPolicy.DENY:
            raise ExtensionError("TOOL_DENIED")
        validate_instance(descriptor.input_schema, dict(arguments))
        stamp = now or datetime.now(UTC)
        return self.store.create_approval(
            call_id=call_id or str(uuid4()),
            conversation_id=conversation_id,
            turn_id=turn_id,
            qualified_name=qualified_tool_name,
            server_revision=descriptor.connection_revision,
            capability_revision=descriptor.capability_revision,
            arguments_hash=arguments_hash(arguments),
            expires_at=stamp + timedelta(minutes=10),
        )

    def decide_approval(
        self,
        *,
        call_id: str,
        approval_id: str,
        decision: str,
        capability_revision_value: str,
        arguments_hash_value: str,
    ) -> dict[str, object]:
        if decision not in {"approve", "deny"}:
            raise ExtensionError("APPROVAL_DECISION_INVALID")
        return self.store.decide_approval(
            call_id=call_id,
            approval_id=approval_id,
            decision=decision,
            capability_revision=capability_revision_value,
            arguments_hash=arguments_hash_value,
        )

    def consume_approval(
        self,
        *,
        call_id: str,
        approval_id: str,
        qualified_tool_name: str,
        capability_revision_value: str,
        arguments_hash_value: str,
    ) -> dict[str, object]:
        return self.store.consume_approval(
            call_id=call_id,
            approval_id=approval_id,
            qualified_name=qualified_tool_name,
            capability_revision=capability_revision_value,
            arguments_hash=arguments_hash_value,
        )

    def revoke_turn(self, turn_id: str) -> int:
        return self.store.revoke_turn(turn_id)

    def revoke_pending_approvals(self) -> int:
        return self.store.revoke_pending_approvals()

    async def call(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        qualified_tool_name: str,
        arguments: Mapping[str, object],
        approval: Mapping[str, str] | None = None,
        timeout: float = 60.0,
        turn_remaining_seconds: float | None = None,
    ) -> McpCallResult:
        descriptor = self.get_tool(qualified_tool_name)
        if descriptor.policy is ToolPolicy.DENY:
            raise ExtensionError("TOOL_DENIED")
        validate_instance(descriptor.input_schema, dict(arguments))
        arg_hash = arguments_hash(arguments)
        if descriptor.policy is ToolPolicy.CONFIRM:
            if approval is None:
                raise ApprovalRequired(
                    self.request_approval(
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        qualified_tool_name=qualified_tool_name,
                        arguments=arguments,
                    )
                )
            self.consume_approval(
                call_id=approval["call_id"],
                approval_id=approval["approval_id"],
                qualified_tool_name=qualified_tool_name,
                capability_revision_value=approval.get(
                    "capability_revision", descriptor.capability_revision
                ),
                arguments_hash_value=approval.get("arguments_hash", arg_hash),
            )
        if turn_remaining_seconds is not None and turn_remaining_seconds <= 0:
            raise ExtensionError("TOOL_BUDGET_EXCEEDED")
        try:
            result = await self.mcp_client.call_tool(
                descriptor.server_id,
                descriptor.tool_name,
                dict(arguments),
                timeout,
                turn_remaining_seconds=turn_remaining_seconds,
            )
        except McpClientError as exc:
            self._audit(
                conversation_id, turn_id, qualified_tool_name, descriptor, arg_hash, exc.code
            )
            raise ExtensionError(exc.code) from exc
        except asyncio.CancelledError as exc:
            self._audit(
                conversation_id,
                turn_id,
                qualified_tool_name,
                descriptor,
                arg_hash,
                "TOOL_CANCELLED",
            )
            raise ExtensionError("TOOL_CANCELLED") from exc
        except Exception as exc:
            self._audit(
                conversation_id,
                turn_id,
                qualified_tool_name,
                descriptor,
                arg_hash,
                "TOOL_OUTCOME_UNKNOWN",
            )
            raise ExtensionError("TOOL_OUTCOME_UNKNOWN") from exc
        if not isinstance(result, McpCallResult):
            self._audit(
                conversation_id,
                turn_id,
                qualified_tool_name,
                descriptor,
                arg_hash,
                "TOOL_OUTCOME_UNKNOWN",
            )
            raise ExtensionError("TOOL_OUTCOME_UNKNOWN")
        try:
            serialized_size = len(result.model_dump_json().encode("utf-8"))
        except (TypeError, ValueError) as exc:
            self._audit(
                conversation_id,
                turn_id,
                qualified_tool_name,
                descriptor,
                arg_hash,
                "TOOL_OUTCOME_UNKNOWN",
            )
            raise ExtensionError("TOOL_OUTCOME_UNKNOWN") from exc
        if serialized_size > MAX_MESSAGE_BYTES:
            self._audit(
                conversation_id,
                turn_id,
                qualified_tool_name,
                descriptor,
                arg_hash,
                "MCP_RESULT_TOO_LARGE",
            )
            raise ExtensionError("MCP_RESULT_TOO_LARGE")
        if result.is_error:
            self._audit(
                conversation_id, turn_id, qualified_tool_name, descriptor, arg_hash, "TOOL_IS_ERROR"
            )
            raise ExtensionError("TOOL_IS_ERROR")
        if descriptor.output_schema is not None and result.structured_content is not None:
            try:
                validate_instance(descriptor.output_schema, result.structured_content, output=True)
            except ExtensionError as exc:
                self._audit(
                    conversation_id,
                    turn_id,
                    qualified_tool_name,
                    descriptor,
                    arg_hash,
                    exc.code,
                )
                raise
        self._audit(conversation_id, turn_id, qualified_tool_name, descriptor, arg_hash, None)
        return result

    def _audit(
        self,
        conversation_id: str,
        turn_id: str,
        name: str,
        descriptor: ToolDescriptor,
        arg_hash: str,
        error: str | None,
    ) -> None:
        if self.workbench is None:
            return
        payload: dict[str, object] = {
            "tool": name,
            "call_id": "redacted",
            "schema_hash": descriptor.schema_hash,
            "capability_revision": descriptor.capability_revision,
            "arguments_hash": arg_hash,
        }
        if error is not None:
            payload["error_code"] = error
        with suppress(ValueError, TypeError):
            self.workbench.append_event(
                conversation_id,
                turn_id,
                "action.failed" if error is not None else "action.completed",
                payload,
            )
