"""A bounded local chat queue, independent of the statistical JobRunner."""

import asyncio
from collections import deque
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, TypedDict
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from bioagent.models.adapters import deepseek_body, error_code
from bioagent.models.profiles import ModelError
from bioagent.models.store import ModelProfileStore
from bioagent.workbench.actions import AnswerAction, ClarifyAction, PlanAnalysisAction, parse_action
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


class _Extra(TypedDict, total=False):
    extra_body: dict[str, object]


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

        async def stream(
            messages: tuple[Message, ...],
        ) -> AsyncGenerator[str | Clarification | dict[str, object], None]:
            # Keep role boundaries; this stage has no analysis/action or approval handler.
            from langchain_core.messages import AIMessage, BaseMessage

            prompt: list[BaseMessage] = [
                SystemMessage(
                    content=(
                        "You explain the local Bio-Agent software and discuss the user's inputs. "
                        "No analysis tools are connected to this chat yet. Never claim an analysis "
                        "was executed or approved. Do not reveal private reasoning "
                        "or invent results."
                    )
                )
            ]
            for message in messages:
                prompt.append(
                    HumanMessage(content=message.content)
                    if message.role == "user"
                    else AIMessage(content=message.content)
                )
            async for chunk in model.astream(prompt):
                if isinstance(chunk.content, str):
                    if chunk.content:
                        yield chunk.content
                else:
                    for block in chunk.content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text")
                            if isinstance(text, str) and text:
                                yield text

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

    def bind_analysis(self, analysis: object) -> None:
        self._analysis = analysis

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
