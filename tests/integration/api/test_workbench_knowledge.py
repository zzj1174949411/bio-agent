import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.knowledge.answers import AnswerService
from bioagent.knowledge.store import KnowledgeError
from bioagent.workbench.actions import parse_action
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.store import WorkbenchStore
from bioagent.workbench.turns import PreparedChat, TurnService

sys.path.insert(0, str(Path(__file__).parents[2] / "unit" / "knowledge"))
from test_retrieval import engine, prepared  # noqa: E402, F401


def test_fixed_revision_never_silently_retrieves_rebuilt_or_new_documents(engine):  # noqa: F811
    engine, doc = engine
    engine.build(doc["id"])
    fixed = engine.snapshot([doc["base_id"]])
    assert engine.search("untrusted", [doc["base_id"]], fixed=fixed).items
    engine.build(doc["id"])
    with pytest.raises(KnowledgeError, match="EVIDENCE_STALE"):
        engine.search("untrusted", [doc["base_id"]], fixed=fixed)


def test_knowledge_action_has_no_model_selectable_scope():
    assert parse_action({"kind": "knowledge_ask", "question": "What does the paper say?"})
    with pytest.raises(ValueError):
        parse_action({"kind": "knowledge_ask", "question": "q", "knowledge_base_ids": [uuid4()]})


def test_pre_knowledge_json_records_restore_with_empty_defaults(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with WorkbenchStore(path) as store:
        chat = store.create_conversation(store.create_project("p").id, "c")
        turn = store.begin_turn(chat.id, uuid4(), "legacy question", None)
        for table in ("conversations", "turns", "messages"):
            for row in store._db.execute(f"SELECT id,record FROM {table}").fetchall():
                record = json.loads(row["record"])
                for field in tuple(record):
                    if "knowledge" in field:
                        del record[field]
                store._db.execute(
                    f"UPDATE {table} SET record=? WHERE id=?", (json.dumps(record), row["id"])
                )
    with WorkbenchStore(path) as store:
        assert store.get_conversation(chat.id).selected_knowledge_base_ids == ()
        restored = store.get_turn(turn.id)
        assert restored.knowledge_base_ids == restored.knowledge_revisions == ()
        assert restored.knowledge_ask_id is None
        assert store.list_messages(chat.id).items[0].knowledge_ask_id is None


def test_chat_knowledge_routes_require_owner_and_validate_selected_library(tmp_path):
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "cp.sqlite",
        workbench_db=tmp_path / "wb.sqlite",
    )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        project = client.post("/api/v1/workbench/projects", json={"title": "p"}).json()
        chat = client.post(
            "/api/v1/workbench/conversations", json={"project_id": project["id"], "title": "c"}
        ).json()
        prefix = f"/api/v1/workbench/conversations/{chat['id']}"
        base = client.post("/api/v1/knowledge/bases", json={"name": "empty"}).json()
        selected = client.patch(prefix, json={"selected_knowledge_base_ids": [base["id"]]})
        assert selected.status_code == 200
        assert selected.json()["selected_knowledge_base_ids"] == [base["id"]]
        invalid = client.patch(prefix, json={"selected_knowledge_base_ids": [str(uuid4())]})
        assert invalid.status_code == 404
        client.cookies.clear()
        for suffix in ["knowledge", "knowledge/events", f"evidence/{uuid4()}/pdf"]:
            response = client.get(f"{prefix}/turns/{uuid4()}/{suffix}")
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "KNOWLEDGE_TURN_MISMATCH"


def test_chat_freezes_selection_and_model_and_revokes_history(engine, tmp_path):  # noqa: F811
    from bioagent.workbench.knowledge import WorkbenchKnowledge

    engine, doc = engine
    engine.build(doc["id"])
    fixed = TurnModelSnapshot(
        provider="ollama",
        model="frozen",
        base_url="http://localhost:11434",
        revision=1,
        thinking="default",
        structured_method="function_calling",
    )
    profile = uuid4()
    gate = asyncio.Event()

    class MockModel:
        async def ainvoke(self, messages):
            evidence = json.loads(messages[-1].content)["evidence"]
            return SimpleNamespace(
                content=json.dumps(
                    {"answer": "trusted answer", "citations": [hit["chunk_id"] for hit in evidence]}
                )
            )

    async def stream(messages):
        await gate.wait()
        yield "unverified literature preamble must not be published"
        yield {"kind": "knowledge_ask", "question": "untrusted text"}

    async def scenario():
        with WorkbenchStore(tmp_path / "wb.sqlite") as store:
            chat = store.create_conversation(store.create_project("p").id, "c")
            store.set_knowledge_selection(chat.id, (UUID(doc["base_id"]),))
            answers = AnswerService(engine, SimpleNamespace(), SimpleNamespace())
            bridge = WorkbenchKnowledge(store, answers)
            service = TurnService(
                store, lambda *_: PreparedChat(fixed, stream, answer_model=MockModel())
            )
            service.bind_knowledge(bridge)
            await service.start()
            turn = await service.submit(chat.id, uuid4(), "question", profile)
            store.set_knowledge_selection(chat.id, ())
            gate.set()
            for _ in range(200):
                turn = store.get_turn(turn.id)
                if turn.status in {"COMPLETED", "FAILED"}:
                    break
                await asyncio.sleep(0.01)
            assert turn.status == "COMPLETED", turn.error_code
            task = bridge.task(chat.id, turn.id)
            assert task.snapshot.model == "frozen" and task.answer == "trusted answer"
            other = store.create_conversation(chat.project_id, "other")
            with pytest.raises(ValueError, match="KNOWLEDGE_TURN_MISMATCH"):
                bridge.task(other.id, turn.id)
            engine.build(doc["id"])
            assert bridge.task(chat.id, turn.id).error_code == "EVIDENCE_STALE"
            assert not any(e.kind == "answer.delta" for e in answers.events(str(task.id), 0))
            assert "trusted answer" not in str(store.list_messages(chat.id))
            assert "trusted answer" not in str(store.list_events(chat.id))
            assert "unverified literature preamble" not in str(store.list_messages(chat.id))
            await service.close()
            await answers.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["cancel", "rebuild_before_action"])
def test_knowledge_turn_cancellation_and_queued_snapshot(engine, tmp_path, mode):  # noqa: F811
    from bioagent.workbench.knowledge import WorkbenchKnowledge

    engine, doc = engine
    engine.build(doc["id"])
    snapshot = TurnModelSnapshot(
        provider="ollama",
        model="mock",
        base_url="http://localhost:11434",
        revision=1,
        thinking="default",
        structured_method="function_calling",
    )

    async def scenario():
        gate, invoked = asyncio.Event(), asyncio.Event()

        class Model:
            async def ainvoke(self, messages):
                invoked.set()
                await asyncio.Event().wait()

        async def stream(messages):
            await gate.wait()
            yield {"kind": "knowledge_ask", "question": "untrusted"}

        with WorkbenchStore(tmp_path / "wb.sqlite") as store:
            chat = store.create_conversation(store.create_project("p").id, "c")
            store.set_knowledge_selection(chat.id, (UUID(doc["base_id"]),))
            answers = AnswerService(engine, SimpleNamespace(), SimpleNamespace())
            bridge = WorkbenchKnowledge(store, answers)
            service = TurnService(
                store, lambda *_: PreparedChat(snapshot, stream, answer_model=Model())
            )
            service.bind_knowledge(bridge)
            await service.start()
            try:
                turn = await service.submit(chat.id, uuid4(), "question", uuid4())
                if mode == "rebuild_before_action":
                    engine.build(doc["id"])
                gate.set()
                if mode == "cancel":
                    await asyncio.wait_for(invoked.wait(), 5)
                    await service.cancel(turn.id)
                for _ in range(200):
                    current = store.get_turn(turn.id)
                    if mode == "cancel" and bridge.task(chat.id, turn.id).status == "CANCELLED":
                        break
                    if mode != "cancel" and current.status == "FAILED":
                        break
                    await asyncio.sleep(0.01)
                current = store.get_turn(turn.id)
                if mode == "cancel":
                    assert current.status == "CANCELLED"
                    task = bridge.task(chat.id, turn.id)
                    assert task.status == "CANCELLED" and task.answer is None
                    assert not any(
                        e.kind == "answer.delta" for e in answers.events(str(task.id), 0)
                    )
                else:
                    assert current.error_code == "EVIDENCE_STALE"
                    assert not invoked.is_set() and current.knowledge_ask_id is None
            finally:
                await service.close()
                await answers.close()

    asyncio.run(scenario())
