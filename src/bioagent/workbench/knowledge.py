"""Bind trusted literature answers to a server-owned chat turn, without copying answer text."""

import asyncio
from typing import Any
from uuid import UUID

from bioagent.knowledge.answers import TERMINAL, AnswerService
from bioagent.knowledge.retrieval_models import AskRequest, AskTask, SearchHit, WikiSnapshot
from bioagent.knowledge.store import KnowledgeError
from bioagent.models.profiles import ModelSnapshot
from bioagent.workbench.actions import KnowledgeAskAction
from bioagent.workbench.models import Turn, WorkbenchError
from bioagent.workbench.store import WorkbenchStore


class WorkbenchKnowledge:
    def __init__(self, store: WorkbenchStore, answers: AnswerService) -> None:
        self.store, self.answers = store, answers

    def snapshot(self, bases: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return self.answers.engine.snapshot([str(key) for key in bases]) if bases else ()

    def wiki_snapshot(self, bases: tuple[UUID, ...]) -> tuple[WikiSnapshot, ...]:
        return self.answers.hybrid.snapshot(bases) if bases else ()

    def task(self, conversation: UUID, turn_id: UUID) -> AskTask:
        turn = self.store.get_turn(turn_id)
        if turn.conversation_id != conversation or turn.knowledge_ask_id is None:
            raise WorkbenchError("KNOWLEDGE_TURN_MISMATCH")
        task = self.answers.get(str(turn.knowledge_ask_id))
        if (
            task.fixed_scope != turn.knowledge_base_ids
            or task.fixed_revisions != turn.knowledge_revisions
            or task.requested_mode != turn.knowledge_mode
            or task.wiki_snapshot != turn.knowledge_wiki_snapshot
        ):
            raise WorkbenchError("KNOWLEDGE_TURN_MISMATCH")
        return task

    def hit(self, conversation: UUID, turn_id: UUID, chunk_id: UUID) -> SearchHit:
        task = self.task(conversation, turn_id)
        if task.status != "COMPLETED":
            raise KnowledgeError(task.error_code or "EVIDENCE_STALE")
        ref = next((ref for ref in task.citations if ref.chunk_id == chunk_id), None)
        if ref is None:
            raise KnowledgeError("EVIDENCE_INVALID")
        self.answers.engine.validate(ref, task.evidence)
        return next(hit for hit in task.evidence if hit.reference == ref)

    async def run(self, turn: Turn, action: KnowledgeAskAction, model: Any) -> None:
        if not turn.knowledge_base_ids:
            raise WorkbenchError("KNOWLEDGE_NOT_SELECTED")
        if turn.model_snapshot is None or turn.profile_id is None or model is None:
            raise WorkbenchError("MODEL_NOT_CONFIGURED")
        task = await self.answers.submit(
            AskRequest(
                question=action.question,
                knowledge_base_ids=turn.knowledge_base_ids,
                model_profile_id=turn.profile_id,
                mode=turn.knowledge_mode,
            ),
            fixed=turn.knowledge_revisions,
            wiki_fixed=turn.knowledge_wiki_snapshot,
            snapshot=ModelSnapshot.model_validate(turn.model_snapshot.model_dump()),
            model=model,
        )
        self.store.update_turn_progress(turn.id, knowledge_ask_id=task.id)
        # Durable chat messages/events contain only this capability ID, never revoked answer text.
        self.store.append_message(
            turn.conversation_id, turn.id, "assistant", "", knowledge_ask_id=task.id
        )
        sequence = 0
        try:
            while True:
                for event in self.answers.events(str(task.id), sequence):
                    sequence = event.sequence
                    if event.kind != "answer.delta":
                        self.store.append_event(
                            turn.conversation_id,
                            turn.id,
                            "knowledge.updated",
                            {
                                "ask_id": str(task.id),
                                "kind": event.kind,
                                "sequence": sequence,
                                **event.data,
                            },
                        )
                task = self.answers.get(str(task.id))
                if task.status in TERMINAL:
                    break
                await asyncio.sleep(0.05)
            if task.status == "FAILED":
                raise WorkbenchError(task.error_code or "KNOWLEDGE_FAILED")
            if task.status == "CANCELLED":
                self.store.cancel_turn(turn.id)
            else:
                self.store.complete_output(turn.id)
        except asyncio.CancelledError:
            await self.answers.cancel(str(task.id))
            raise
