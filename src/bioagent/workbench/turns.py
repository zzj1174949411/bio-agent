"""A bounded local chat queue, independent of the statistical JobRunner."""

import asyncio
import json
import re
from collections import deque
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from bioagent.geo.service import GeoServiceError
from bioagent.models.adapters import deepseek_body, error_code
from bioagent.models.profiles import ModelError
from bioagent.models.store import ModelProfileStore
from bioagent.workbench.actions import (
    AnswerAction,
    ClarifyAction,
    GeoImportAction,
    GeoLookupAction,
    PlanAnalysisAction,
    parse_action,
)
from bioagent.workbench.models import Message, Turn, TurnModelSnapshot, TurnStatus, WorkbenchError
from bioagent.workbench.store import WorkbenchStore


@dataclass(frozen=True)
class Clarification:
    """Trusted driver signal; arbitrary model text is never parsed as a control action."""

    question: str


@dataclass(frozen=True)
class PreparedChat:
    snapshot: TurnModelSnapshot
    stream: Callable[
        [tuple[Message, ...]], AsyncGenerator[str | Clarification | dict[str, object], None]
    ] = field(repr=False)


ChatFactory = Callable[[UUID, TurnModelSnapshot | None], PreparedChat]


class GeoConversationService(Protocol):
    def create_source(
        self,
        accession: str,
        *,
        conversation_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, object]: ...

    def get_source(self, source_id: UUID | str) -> dict[str, object]: ...


class _Extra(TypedDict, total=False):
    extra_body: dict[str, object]


_GEO_TOOLS: tuple[dict[str, object], ...] = (
    {
        "type": "function",
        "function": {
            "name": "geo_lookup",
            "description": "Discover one user-selected GEO series by accession.",
            "parameters": {
                "type": "object",
                "properties": {"accession": {"type": "string", "pattern": "^GSE[1-9][0-9]*$"}},
                "required": ["accession"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geo_import",
            "description": "Suggest a discovered GEO candidate; never downloads it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "format": "uuid"},
                    "candidate_id": {"type": "string", "format": "uuid"},
                    "revision": {"type": "integer", "minimum": 1},
                },
                "required": ["source_id", "candidate_id", "revision"],
                "additionalProperties": False,
            },
        },
    },
)


def _validated_geo_action(name: object, args: object) -> dict[str, object]:
    """Validate a streamed provider tool call before exposing it to the turn queue."""

    if name not in {"geo_lookup", "geo_import"} or not isinstance(args, dict):
        raise ValueError("MODEL_ACTION_INVALID")
    if "kind" in args:
        raise ValueError("MODEL_ACTION_INVALID")
    try:
        action = parse_action({"kind": name, **args})
    except (TypeError, ValueError) as error:
        raise ValueError("MODEL_ACTION_INVALID") from error
    if not isinstance(action, (GeoLookupAction, GeoImportAction)):
        raise ValueError("MODEL_ACTION_INVALID")
    return action.model_dump(mode="json")


class ConfiguredChatFactory:
    """Resolve credentials for this request and bind a fixed configuration before enqueueing."""

    def __init__(self, profiles: ModelProfileStore) -> None:
        self._profiles = profiles

    def __call__(self, identity: UUID, fixed: TurnModelSnapshot | None) -> PreparedChat:
        profile, secret = self._profiles.request_config(identity)
        snapshot = fixed or profile.snapshot()
        if snapshot.provider == "ollama":
            model: BaseChatModel = ChatOllama(
                base_url=snapshot.base_url, model=snapshot.model, client_kwargs={"timeout": 60}
            )
        else:
            if secret is None:
                raise ModelError("MODEL_NOT_CONFIGURED")
            extra: _Extra = (
                {"extra_body": deepseek_body()} if snapshot.provider == "deepseek" else {}
            )
            model = ChatOpenAI(
                api_key=secret,
                base_url=snapshot.base_url,
                model=snapshot.model,
                timeout=60,
                max_retries=0,
                **extra,
            )

        action_model: Any = model
        bind_tools = getattr(model, "bind_tools", None)
        if callable(bind_tools):
            try:
                action_model = bind_tools(list(_GEO_TOOLS))
            except (NotImplementedError, TypeError):
                # Providers without native tool calls retain text-only chat;
                # they cannot manufacture an unvalidated action payload.
                action_model = model

        async def stream(
            messages: tuple[Message, ...],
        ) -> AsyncGenerator[str | Clarification | dict[str, object], None]:
            # Keep role boundaries; this stage has no analysis/action or approval handler.
            from langchain_core.messages import AIMessage, BaseMessage

            prompt: list[BaseMessage] = [
                SystemMessage(
                    content=(
                        "You explain the local Bio-Agent software and discuss the user's inputs. "
                        "You may call only the supplied GEO tools when appropriate. A GEO tool "
                        "only proposes a constrained action; the user confirmation card controls "
                        "network work. Never claim an analysis was executed or approved. Do not "
                        "reveal private reasoning or invent results."
                    )
                )
            ]
            for message in messages:
                prompt.append(
                    HumanMessage(content=message.content)
                    if message.role == "user"
                    else AIMessage(content=message.content)
                )
            emitted: set[str] = set()
            pending_names: dict[str, str] = {}
            pending_args: dict[str, str] = {}
            async for chunk in action_model.astream(prompt):
                calls = getattr(chunk, "tool_calls", ()) or getattr(chunk, "tool_call_chunks", ())
                for position, call in enumerate(
                    calls if isinstance(calls, (list, tuple)) else ()
                ):
                    if not isinstance(call, dict):
                        continue
                    index = call.get("index")
                    raw_id = call.get("id")
                    id_key = f"id:{raw_id}" if raw_id is not None else ""
                    index_key = f"index:{index}" if index is not None else ""
                    # LangChain continuation chunks commonly retain ``index``
                    # but omit the provider call id, so index is the stable
                    # reassembly key whenever it is available.
                    call_id = index_key or id_key or f"position:{position}"
                    raw_name = call.get("name")
                    if raw_name is not None:
                        if not isinstance(raw_name, str) or raw_name not in {
                            "geo_lookup",
                            "geo_import",
                        }:
                            raise ValueError("MODEL_ACTION_INVALID")
                        if id_key:
                            pending_names[id_key] = raw_name
                        if index_key:
                            pending_names[index_key] = raw_name
                        pending_names[call_id] = raw_name
                    name = (
                        pending_names.get(id_key)
                        or pending_names.get(index_key)
                        or pending_names.get(call_id)
                    )
                    if name is None:
                        # LangChain emits continuation chunks without a name;
                        # an unknown first chunk is invalid and must not become
                        # a text-only successful turn.
                        if call.get("args") not in (None, ""):
                            raise ValueError("MODEL_ACTION_INVALID")
                        continue
                    args = call.get("args")
                    if isinstance(args, str):
                        pending_args[call_id] = pending_args.get(call_id, "") + args
                        try:
                            args = json.loads(pending_args[call_id])
                        except json.JSONDecodeError:
                            continue
                    if not isinstance(args, dict):
                        raise ValueError("MODEL_ACTION_INVALID")
                    payload = _validated_geo_action(name, args)
                    marker = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                    if marker not in emitted:
                        emitted.add(marker)
                        yield payload
                    pending_args.pop(call_id, None)
                content = getattr(chunk, "content", "")
                if isinstance(content, str):
                    if content:
                        yield content
                else:
                    for block in content if isinstance(content, list) else ():
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text")
                            if isinstance(text, str) and text:
                                yield text
            if pending_args:
                raise ValueError("MODEL_ACTION_INVALID")

        return PreparedChat(snapshot, stream)


@dataclass(frozen=True)
class _Job:
    turn_id: UUID
    model: PreparedChat = field(repr=False)


class TurnService:
    def __init__(
        self,
        store: WorkbenchStore,
        prepare: ChatFactory,
        *,
        workers: int = 2,
        analysis: object | None = None,
        geo: GeoConversationService | None = None,
    ) -> None:
        if not 1 <= workers <= 8:
            raise ValueError("invalid chat worker count")
        self.store = store
        self._prepare = prepare
        self._worker_count = workers
        self._pending: deque[_Job] = deque()
        self._wake = asyncio.Event()
        self._submit_lock = asyncio.Lock()
        self._workers: list[asyncio.Task[None]] = []
        self._running: dict[UUID, asyncio.Task[None]] = {}
        self._closed = False
        self._analysis = analysis
        self._geo = geo

    def bind_analysis(self, analysis: object) -> None:
        self._analysis = analysis

    def bind_geo(self, geo: GeoConversationService) -> None:
        self._geo = geo

    def resume_geo_ready(self, state: dict[str, object]) -> None:
        """Create a normal approval-gated plan after a confirmed GEO import.

        This is deliberately not an execution callback: AnalysisService creates
        an awaiting-approval run, so a READY import alone still has zero R
        attempts.
        """
        dataset_id = state.get("dataset_id")
        context = state.get("context")
        if not isinstance(dataset_id, str) or not isinstance(context, dict):
            return
        turn_id = context.get("turn_id")
        source_id = state.get("published_source_id") or state.get("source_id")
        if not isinstance(turn_id, str) or not isinstance(source_id, str):
            return
        try:
            turn = self.store.get_turn(turn_id)
        except (ValueError, TypeError):
            return
        if turn.run_id is not None or self._analysis is None:
            return
        messages = self.store.list_messages(turn.conversation_id, limit=20).items
        goal = next(
            (
                item.content
                for item in messages
                if item.role == "user" and item.turn_id == turn.id
            ),
            "GEO analysis",
        )
        try:
            run_id = self._analysis_service().create_run(
                dataset_id=dataset_id,
                goal=goal,
                agent_context={
                    "conversation_id": str(turn.conversation_id),
                    "turn_id": str(turn.id),
                    "model_snapshot": turn.model_snapshot.model_dump(mode="json")
                    if turn.model_snapshot
                    else None,
                    "skill_names": [],
                    "skill_hashes": [],
                    "source_id": source_id,
                },
            )
            self.store.set_run_id(turn.id, UUID(run_id))
            self.store.append_event(
                turn.conversation_id,
                turn.id,
                "run.updated",
                {"run_id": run_id, "status": "AWAITING_APPROVAL", "source_id": source_id},
            )
        except Exception:
            # The import remains READY and can be retried explicitly; never
            # turn a completed evidence import into a statistical execution.
            return

    async def start(self) -> None:
        if self._workers:
            return
        self.store.interrupt_unfinished()
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self._worker_count)]

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.store.interrupt_unfinished()
        self._pending.clear()
        for task in (*self._workers, *self._running.values()):
            task.cancel()
        await asyncio.gather(*self._workers, *self._running.values(), return_exceptions=True)

    def _capacity(self) -> None:
        if self._closed or not self._workers:
            raise WorkbenchError("TURN_SERVICE_UNAVAILABLE")
        if len(self._pending) >= 32:
            raise WorkbenchError("TURN_QUEUE_FULL")

    async def submit(
        self,
        conversation_id: UUID,
        client_request_id: UUID,
        text: str,
        profile_id: UUID | None,
        dataset_ids: tuple[UUID, ...] = (),
    ) -> Turn:
        async with self._submit_lock:
            conversation = self.store.get_conversation(conversation_id)
            duplicate = self.store.find_request(conversation_id, client_request_id)
            if duplicate is not None:
                self.store.verify_request(duplicate, text, profile_id, dataset_ids)
                return duplicate
            if self.store.active_turn(conversation_id) is not None:
                raise WorkbenchError("TURN_BUSY")
            self._capacity()
            selected = profile_id or conversation.selected_profile_id
            if selected is None:
                raise WorkbenchError("MODEL_NOT_CONFIGURED")
            prepared = await asyncio.to_thread(self._prepare, selected, None)
            self._capacity()
            turn = self.store.begin_turn(
                conversation_id,
                client_request_id,
                text,
                prepared.snapshot,
                dataset_ids=dataset_ids,
                profile_id=selected,
                requested_profile_id=profile_id,
            )
            self._pending.append(_Job(turn.id, prepared))
            self._wake.set()
            return turn

    async def cancel(self, turn_id: UUID) -> Turn:
        turn = self.store.cancel_turn(turn_id)
        self._pending = deque(job for job in self._pending if job.turn_id != turn_id)
        if task := self._running.get(turn_id):
            task.cancel()
        return turn

    async def respond(
        self, turn_id: UUID, request_id: UUID, revision: int, action: str, value: str
    ) -> Turn:
        async with self._submit_lock:
            turn = self.store.get_turn(turn_id)
            pending = turn.pending_input
            if (
                action != "clarify"
                or turn.status != TurnStatus.WAITING_USER
                or pending is None
                or pending.request_id != request_id
                or pending.revision != revision
            ):
                raise WorkbenchError("INPUT_RESPONSE_CONFLICT")
            self._capacity()
            if turn.profile_id is None:
                raise WorkbenchError("MODEL_NOT_CONFIGURED")
            prepared = await asyncio.to_thread(self._prepare, turn.profile_id, turn.model_snapshot)
            self._capacity()
            updated = self.store.accept_response(turn_id, request_id, revision, value)
            self._pending.append(_Job(turn_id, prepared))
            self._wake.set()
            return updated

    async def _worker(self) -> None:
        while not self._closed:
            await self._wake.wait()
            if not self._pending:
                self._wake.clear()
                continue
            job = self._pending.popleft()
            if self.store.get_turn(job.turn_id).status != TurnStatus.QUEUED:
                continue
            task = asyncio.create_task(self._execute(job))
            self._running[job.turn_id] = task
            try:
                await task
            except asyncio.CancelledError:
                if self._closed:
                    return
            finally:
                self._running.pop(job.turn_id, None)

    async def _execute(self, job: _Job) -> None:
        try:
            if self._closed or self.store.get_turn(job.turn_id).status != TurnStatus.QUEUED:
                return
            turn = self.store.update_turn(job.turn_id, TurnStatus.RUNNING)
            recent = self.store.list_messages(turn.conversation_id, limit=20).items
            messages = []
            size = 0
            for message in recent:
                if message.partial:
                    continue
                size += len(message.content.encode("utf-8"))
                if size > 64 * 1024:
                    break
                messages.append(message)
            async with (
                asyncio.timeout(120),
                aclosing(job.model.stream(tuple(reversed(messages)))) as outputs,
            ):
                action_count = 0
                async for output in outputs:
                    if self._closed:
                        return
                    if isinstance(output, dict):
                        action_count += 1
                        if action_count > 8:
                            raise WorkbenchError("TURN_BUDGET_EXCEEDED")
                        action = parse_action(output)
                        if isinstance(action, AnswerAction):
                            output = action.text
                        elif isinstance(action, ClarifyAction):
                            output = Clarification(action.question)
                        elif isinstance(action, PlanAnalysisAction):
                            if self._analysis is None:
                                raise WorkbenchError("ANALYSIS_UNAVAILABLE")
                            await self._run_plan_action(turn, action)
                            return
                        elif isinstance(action, GeoLookupAction):
                            await self._run_geo_lookup(turn, action)
                            return
                        elif isinstance(action, GeoImportAction):
                            await self._run_geo_import_suggestion(turn, action)
                            return
                    if isinstance(output, Clarification):
                        self.store.require_input(turn.id, output.question)
                        return
                    if not isinstance(output, str):
                        raise WorkbenchError("MODEL_OUTPUT_INVALID")
                    if output and not self.store.append_delta(turn.id, output):
                        return
            if not self._closed:
                self.store.complete_output(turn.id)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._closed:
                code = error.code if isinstance(error, WorkbenchError) else error_code(error)
                self.store.fail_turn(job.turn_id, code)

    async def _run_plan_action(self, turn: Turn, action: PlanAnalysisAction) -> None:
        dataset_ids = {
            dataset_id
            for message in self.store.list_messages(turn.conversation_id, limit=20).items
            for dataset_id in message.dataset_ids
        }
        if action.dataset_id not in dataset_ids:
            raise WorkbenchError("DATASET_NOT_SELECTED")
        run_id = await asyncio.to_thread(
            self._analysis_service().create_run,
            dataset_id=str(action.dataset_id),
            goal=action.goal,
            agent_context={
                "conversation_id": str(turn.conversation_id),
                "turn_id": str(turn.id),
                "model_snapshot": turn.model_snapshot.model_dump(mode="json")
                if turn.model_snapshot
                else None,
                "skill_names": [],
                "skill_hashes": [],
                "source_id": None,
            },
        )
        self.store.set_run_id(turn.id, UUID(run_id))
        self.store.require_input(turn.id, "请在原分析审批卡中批准、修改或拒绝该计划。")

    def _analysis_service(self) -> Any:
        if self._analysis is None:
            raise WorkbenchError("ANALYSIS_UNAVAILABLE")
        return self._analysis

    async def _run_geo_lookup(self, turn: Turn, action: GeoLookupAction) -> None:
        if self._geo is None:
            raise WorkbenchError("GEO_UNAVAILABLE")
        user_messages = [
            message
            for message in self.store.list_messages(turn.conversation_id, limit=20).items
            if message.role == "user" and message.turn_id == turn.id
        ]
        latest_user = max(user_messages, key=lambda message: message.updated_at, default=None)
        accessions = {
            value.upper()
            for value in (
                re.findall(
                    r"\bGSE[1-9][0-9]*\b", latest_user.content, flags=re.IGNORECASE
                )
                if latest_user is not None
                else ()
            )
        }
        if len(accessions) > 1:
            choices = ", ".join(sorted(accessions))
            self.store.require_input(turn.id, f"检测到多个 GEO 编号（{choices}）。请选择一个继续。")
            return
        if len(accessions) != 1 or action.accession != next(iter(accessions), ""):
            self.store.require_input(
                turn.id,
                "请先在当前消息中提供一个与 GEO 动作一致的 GSE 编号。",
            )
            return
        try:
            source = await asyncio.to_thread(
                self._geo.create_source,
                action.accession,
                conversation_id=str(turn.conversation_id),
                turn_id=str(turn.id),
            )
        except GeoServiceError as error:
            raise WorkbenchError(error.code) from error
        source_id = source.get("id") if isinstance(source, dict) else None
        if not isinstance(source_id, str):
            raise WorkbenchError("GEO_UNAVAILABLE")
        self.store.set_geo_source(turn.conversation_id, UUID(source_id))
        self.store.append_event(
            turn.conversation_id, turn.id, "geo.source", {"source_id": source_id}
        )
        self.store.require_input(turn.id, "请在 GEO 来源卡中确认可下载的 counts 候选文件。")

    async def _run_geo_import_suggestion(self, turn: Turn, action: GeoImportAction) -> None:
        selected_source = self.store.get_conversation(turn.conversation_id).geo_source_id
        if action.source_id != selected_source:
            raise WorkbenchError("GEO_SOURCE_NOT_SELECTED")
        if self._geo is None:
            raise WorkbenchError("GEO_UNAVAILABLE")
        try:
            source = await asyncio.to_thread(self._geo.get_source, action.source_id)
        except GeoServiceError as error:
            raise WorkbenchError(error.code) from error
        source_payload = source.get("source")
        candidates = (
            source_payload.get("candidates", ()) if isinstance(source_payload, dict) else ()
        )
        if not any(
            isinstance(candidate, dict)
            and candidate.get("id") == str(action.candidate_id)
            and candidate.get("source_id") == str(action.source_id)
            for candidate in candidates
        ):
            raise WorkbenchError("GEO_CANDIDATE_NOT_FOUND")
        self.store.append_event(
            turn.conversation_id,
            turn.id,
            "geo.import_suggested",
            {
                "source_id": str(action.source_id),
                "candidate_id": str(action.candidate_id),
                "revision": action.revision,
            },
        )
        self.store.require_input(turn.id, "请确认候选文件后再开始下载；模型建议不会自动下载。")
