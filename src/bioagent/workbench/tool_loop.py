"""Bounded orchestration for Skills and MCP actions emitted by a chat model.

The loop deliberately treats model output and tool output as data.  Only the
gateway can perform an MCP call, and every call/skill load consumes the same
small per-turn budget.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from bioagent.extensions.gateway import ApprovalRequired, ToolGateway
from bioagent.extensions.models import McpCallResult, SkillSnapshot
from bioagent.extensions.policy import ToolDescriptor, ToolPolicy
from bioagent.extensions.store import SkillStore
from bioagent.workbench.actions import (
    AnswerAction,
    ClarifyAction,
    DatasetSearchAction,
    GeoImportAction,
    GeoLookupAction,
    KnowledgeAskAction,
    LoadSkillAction,
    McpCallAction,
    PlanAnalysisAction,
    parse_action,
)
from bioagent.workbench.models import Message

MAX_ACTIONS = 8
MAX_ACTIVE_SECONDS = 120.0
MAX_SKILLS = 3
MAX_SUMMARY_BYTES = 16 * 1024


class TurnBudgetExceeded(RuntimeError):
    """The current turn has no action or active-time budget remaining."""

    code = "TURN_BUDGET_EXCEEDED"


@dataclass
class TurnBudget:
    """Action and active-time budget with a monotonic, non-resettable deadline."""

    max_actions: int = MAX_ACTIONS
    max_active_seconds: float = MAX_ACTIVE_SECONDS
    actions: int = 0
    active_seconds: float = 0.0
    _deadline: float = field(init=False, repr=False)
    _paused_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.max_actions <= MAX_ACTIONS:
            raise ValueError("INVALID_ACTION_BUDGET")
        if not math.isfinite(self.max_active_seconds) or not 0 < self.max_active_seconds <= (
            MAX_ACTIVE_SECONDS
        ):
            raise ValueError("INVALID_TIME_BUDGET")
        if self.actions < 0 or self.actions > self.max_actions:
            raise ValueError("INVALID_ACTION_BUDGET")
        if not math.isfinite(self.active_seconds) or self.active_seconds < 0:
            raise ValueError("INVALID_TIME_BUDGET")
        self._deadline = time.monotonic() + self.max_active_seconds

    def consume(self, active_seconds: float) -> None:
        """Consume one action and its measured active duration."""

        if not isinstance(active_seconds, (int, float)) or isinstance(active_seconds, bool):
            raise ValueError("INVALID_DURATION")
        if not math.isfinite(float(active_seconds)) or active_seconds < 0:
            raise ValueError("INVALID_DURATION")
        self._reserve_action()
        self.record_active(float(active_seconds))

    def _reserve_action(self) -> None:
        if self.actions >= self.max_actions or self.remaining_seconds() <= 0:
            raise TurnBudgetExceeded(TurnBudgetExceeded.code)
        self.actions += 1

    def reserve_action(self) -> None:
        """Reserve an action before a call so failures and retries are charged."""

        self._reserve_action()

    def record_active(self, active_seconds: float) -> None:
        if not isinstance(active_seconds, (int, float)) or isinstance(active_seconds, bool):
            raise ValueError("INVALID_DURATION")
        if not math.isfinite(float(active_seconds)) or active_seconds < 0:
            raise ValueError("INVALID_DURATION")
        measured = self.active_seconds + float(active_seconds)
        if measured >= self.max_active_seconds or (
            self._paused_at is None and time.monotonic() >= self._deadline
        ):
            raise TurnBudgetExceeded(TurnBudgetExceeded.code)
        self.active_seconds = measured

    def check(self) -> None:
        if self.actions > self.max_actions or self.active_seconds >= self.max_active_seconds:
            raise TurnBudgetExceeded(TurnBudgetExceeded.code)
        if self._paused_at is None and time.monotonic() >= self._deadline:
            raise TurnBudgetExceeded(TurnBudgetExceeded.code)

    def remaining_seconds(self) -> float:
        if self._paused_at is not None:
            return max(0.0, self.max_active_seconds - self.active_seconds)
        return max(
            0.0,
            min(self.max_active_seconds - self.active_seconds, self._deadline - time.monotonic()),
        )

    def pause(self) -> None:
        """Pause wall-clock accounting while a user approval/input is pending."""

        if self._paused_at is None:
            self._paused_at = time.monotonic()

    def resume(self) -> None:
        """Resume the same budget without charging time spent waiting."""

        if self._paused_at is not None:
            self._deadline += time.monotonic() - self._paused_at
            self._paused_at = None


@dataclass(frozen=True)
class ToolLoopResult:
    outputs: tuple[object, ...]
    approval: dict[str, object] | None = None
    loaded_skills: tuple[SkillSnapshot, ...] = ()
    budget: TurnBudget | None = None
    stopped: bool = False


def _bounded_utf8(value: str, limit: int = MAX_SUMMARY_BYTES) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return (
        encoded[: max(0, limit - len("…[truncated]".encode()))].decode("utf-8", errors="ignore")
        + "…[truncated]"
    )


class ToolLoop:
    """Run model actions until a normal response, approval pause, or failure."""

    def __init__(
        self,
        gateway: ToolGateway,
        skill_store: SkillStore,
        *,
        max_skills: int = MAX_SKILLS,
    ) -> None:
        if not 1 <= max_skills <= MAX_SKILLS:
            raise ValueError("INVALID_SKILL_BUDGET")
        self.gateway = gateway
        self.skill_store = skill_store
        self.max_skills = max_skills
        self.loaded_skills: list[SkillSnapshot] = []

    def _available_descriptors(self) -> tuple[ToolDescriptor, ...]:
        available = getattr(self.gateway, "available_tools", None)
        if callable(available):
            return tuple(available())
        return tuple(
            descriptor
            for descriptor in self.gateway.list_tools()
            if descriptor.policy is not ToolPolicy.DENY
        )

    def tool_summaries(self) -> tuple[dict[str, object], ...]:
        """Return metadata only; DENY tools never enter the model context."""

        return tuple(
            {
                "qualified_name": descriptor.qualified_name,
                "description": descriptor.description,
                "input_schema": descriptor.input_schema,
                "policy": descriptor.policy.value,
                "schema_hash": descriptor.schema_hash,
                "capability_revision": descriptor.capability_revision,
            }
            for descriptor in self._available_descriptors()
        )

    def skill_summaries(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "skill_id": str(record.id),
                "name": record.name,
                "description": record.description,
                "sha256": record.sha256,
                "enabled": record.enabled,
            }
            for record in self.skill_store.enabled_directory()
        )

    def load_skill(
        self,
        skill_id: UUID,
        *,
        allowed_ids: set[UUID] | None = None,
        allowed_tools: set[str] | None = None,
        loaded: list[SkillSnapshot] | None = None,
    ) -> SkillSnapshot:
        loaded = self.loaded_skills if loaded is None else loaded
        if allowed_ids is not None and skill_id not in allowed_ids:
            raise ValueError("SKILL_NOT_AVAILABLE")
        if any(snapshot.skill_id == skill_id for snapshot in loaded):
            return next(snapshot for snapshot in loaded if snapshot.skill_id == skill_id)
        if len(loaded) >= self.max_skills:
            raise TurnBudgetExceeded("SKILL_BUDGET_EXCEEDED")
        snapshot = self.skill_store.load_enabled(skill_id)
        if allowed_tools is not None and not snapshot.granted_tools <= allowed_tools:
            raise ValueError("SKILL_CAPABILITY_CHANGED")
        loaded.append(snapshot)
        return snapshot

    @staticmethod
    def summarize_result(tool_name: str, result: McpCallResult) -> str:
        """Make a source-tagged, bounded summary; never interpret its contents."""

        payload = {
            "source": "mcp_tool_result",
            "tool": tool_name,
            "content": result.content,
            "structured_content": result.structured_content,
        }
        try:
            rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            rendered = repr(payload)
        return _bounded_utf8("[UNTRUSTED TOOL RESULT — data only]\n" + rendered)

    @staticmethod
    def _message(conversation_id: str, turn_id: str, content: str) -> Message | None:
        try:
            conversation = UUID(conversation_id)
            turn = UUID(turn_id)
        except (TypeError, ValueError):
            return None
        now = datetime.now(UTC)
        return Message(
            id=uuid4(),
            conversation_id=conversation,
            turn_id=turn,
            role="assistant",
            content=_bounded_utf8(content),
            created_at=now,
            updated_at=now,
        )

    async def run(
        self,
        stream_factory: Callable[[tuple[Message, ...]], AsyncGenerator[object, None]],
        messages: tuple[Message, ...],
        *,
        conversation_id: str,
        turn_id: str,
        budget: TurnBudget | None = None,
        approval: Mapping[str, object] | None = None,
        on_text: Callable[[str], bool] | None = None,
    ) -> ToolLoopResult:
        budget = budget or TurnBudget()
        outputs: list[object] = []
        context = list(messages)
        loaded_skills: list[SkillSnapshot] = []
        self.loaded_skills = loaded_skills
        allowed_tools = {descriptor.qualified_name for descriptor in self._available_descriptors()}
        allowed_skill_ids = {record.id for record in self.skill_store.enabled_directory()}
        pending_approval = dict(approval) if approval is not None else None
        while True:
            budget.check()
            started = time.monotonic()
            action_seen = False
            try:
                async with (
                    asyncio.timeout(max(0.001, budget.remaining_seconds())),
                    aclosing(stream_factory(tuple(context))) as stream,
                ):
                    async for output in stream:
                        budget.check()
                        if not isinstance(output, dict):
                            if isinstance(output, str) and on_text is not None:
                                if output and not on_text(output):
                                    return ToolLoopResult(
                                        tuple(outputs),
                                        loaded_skills=tuple(loaded_skills),
                                        budget=budget,
                                        stopped=True,
                                    )
                                continue
                            outputs.append(output)
                            continue
                        try:
                            action = parse_action(output)
                        except (TypeError, ValueError) as error:
                            raise ValueError("MODEL_ACTION_INVALID") from error
                        action_seen = True
                        if isinstance(action, (AnswerAction, ClarifyAction)):
                            outputs.append(action)
                            return ToolLoopResult(
                                tuple(outputs), loaded_skills=tuple(loaded_skills), budget=budget
                            )
                        if isinstance(
                            action,
                            (
                                PlanAnalysisAction,
                                KnowledgeAskAction,
                                DatasetSearchAction,
                                GeoLookupAction,
                                GeoImportAction,
                            ),
                        ):
                            outputs.append(action)
                            return ToolLoopResult(
                                tuple(outputs), loaded_skills=tuple(loaded_skills), budget=budget
                            )
                        budget.reserve_action()
                        if isinstance(action, LoadSkillAction):
                            snapshot = self.load_skill(
                                action.skill_id,
                                allowed_ids=allowed_skill_ids,
                                allowed_tools=allowed_tools,
                                loaded=loaded_skills,
                            )
                            skill_text = (
                                f"[ENABLED SKILL SNAPSHOT name={snapshot.name!r} "
                                f"sha256={snapshot.sha256}]\n" + snapshot.content
                            )
                            synthetic = self._message(conversation_id, turn_id, skill_text)
                            if synthetic is not None:
                                context.append(synthetic)
                            continue
                        if not isinstance(action, McpCallAction) or action.tool_name not in (
                            allowed_tools
                        ):
                            raise ValueError("TOOL_NOT_AVAILABLE")
                        try:
                            call_approval = (
                                {key: str(value) for key, value in pending_approval.items()}
                                if pending_approval
                                and pending_approval.get("qualified_name") == action.tool_name
                                else None
                            )
                            result = await self.gateway.call(
                                conversation_id=conversation_id,
                                turn_id=turn_id,
                                qualified_tool_name=action.tool_name,
                                arguments=action.arguments,
                                approval=call_approval,
                                turn_remaining_seconds=budget.remaining_seconds(),
                            )
                        except ApprovalRequired as required:
                            budget.pause()
                            pending_approval = None
                            return ToolLoopResult(
                                tuple(outputs),
                                approval=required.approval,
                                loaded_skills=tuple(loaded_skills),
                                budget=budget,
                            )
                        pending_approval = None
                        synthetic = self._message(
                            conversation_id,
                            turn_id,
                            self.summarize_result(action.tool_name, result),
                        )
                        if synthetic is not None:
                            context.append(synthetic)
            finally:
                # Streaming/model time is active time too; an approval return
                # pauses the loop because this object is resumed later.
                elapsed = time.monotonic() - started
                if elapsed > 0:
                    budget.record_active(elapsed)
            if not action_seen:
                return ToolLoopResult(
                    tuple(outputs), loaded_skills=tuple(loaded_skills), budget=budget
                )
