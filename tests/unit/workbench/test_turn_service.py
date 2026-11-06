import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from bioagent.workbench.events import encode_sse, event_cursor, stream_events
from bioagent.workbench.models import TurnModelSnapshot, TurnStatus
from bioagent.workbench.store import WorkbenchStore
from bioagent.workbench.turns import Clarification, ConfiguredChatFactory, PreparedChat, TurnService


def snapshot(model="mock-a"):
    return TurnModelSnapshot(
        provider="ollama",
        model=model,
        base_url="http://localhost:11434",
        revision=1,
        structured_method="function_calling",
        thinking="default",
    )


def chat(store):
    return store.create_conversation(store.create_project("RNA").id, "chat")


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def test_sse_content_cannot_inject_event():
    frame = encode_sse(7, "message.delta", {"text": "你好\n\nid: 99"})
    assert frame.startswith("id: 7\nevent: message.delta\n")
    assert frame.count("\ndata: ") == 1
    assert json.loads(frame.split("data: ", 1)[1]) == {"text": "你好\n\nid: 99"}
    with pytest.raises(ValueError):
        encode_sse(1, "bad\nevent: x", {})


@pytest.mark.parametrize("after,last,expected", [(None, None, 0), ("4", "7", 7), ("8", "2", 8)])
def test_cursor_uses_larger_valid_value(after, last, expected):
    assert event_cursor(after, last) == expected


@pytest.mark.parametrize("value", ["-1", "bad", "1.5", "", "1\n", str(2**63)])
def test_cursor_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        event_cursor(value, "5")
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        event_cursor("5", value)


def test_background_isolated_conversations_idempotency_and_frozen_snapshot(tmp_path):
    async def scenario(store):
        release = asyncio.Event()
        started = asyncio.Event()
        calls = []
        current = [snapshot()]

        def prepare(profile_id, fixed=None):
            selected = fixed or current[0]

            async def answer(messages):
                calls.append((selected.model, messages[-1].content))
                if messages[-1].content == "slow":
                    started.set()
                    yield "part"
                    await release.wait()
                yield "done"

            return PreparedChat(selected, answer)

        service = TurnService(store, prepare)
        await service.start()
        try:
            first, second = chat(store), chat(store)
            request, profile_id, dataset_id = uuid4(), uuid4(), uuid4()
            one = await service.submit(first.id, request, "slow", profile_id, (dataset_id,))
            await started.wait()
            current[0] = snapshot("mock-b")
            duplicate = await service.submit(first.id, request, "slow", profile_id, (dataset_id,))
            assert duplicate.id == one.id
            two = await service.submit(second.id, uuid4(), "fast", profile_id)
            await until(lambda: store.get_turn(two.id).status == TurnStatus.COMPLETED)
            assert store.get_turn(one.id).status == TurnStatus.RUNNING
            assert store.get_turn(one.id).model_snapshot.model == "mock-a"
            release.set()
            await until(lambda: store.get_turn(one.id).status == TurnStatus.COMPLETED)
            assert calls == [("mock-a", "slow"), ("mock-b", "fast")]
            messages = store.list_messages(first.id).items
            assert any(m.content == "partdone" and not m.partial for m in messages)
            assert any(m.dataset_ids == (dataset_id,) for m in messages)
            with pytest.raises(ValueError, match="REQUEST_ID_CONFLICT"):
                await service.submit(first.id, request, "changed", profile_id)
        finally:
            release.set()
            await service.close()

    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        asyncio.run(asyncio.wait_for(scenario(store), timeout=10))


def test_queue_capacity_cancel_and_late_output_never_revive(tmp_path):
    async def scenario(store):
        started = asyncio.Event()
        late = asyncio.Event()

        def prepare(profile_id, fixed=None):
            async def answer(messages):
                started.set()
                yield "partial"
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    late.set()
                    yield "late"

            return PreparedChat(snapshot(), answer)

        service = TurnService(store, prepare, workers=1)
        await service.start()
        try:
            first = chat(store)
            turn = await service.submit(first.id, uuid4(), "start", uuid4())
            await started.wait()
            queued = []
            for _ in range(32):
                c = chat(store)
                queued.append(await service.submit(c.id, uuid4(), "queued", uuid4()))
            overflow = chat(store)
            with pytest.raises(ValueError, match="TURN_QUEUE_FULL"):
                await service.submit(overflow.id, uuid4(), "full", uuid4())
            assert not store.list_messages(overflow.id).items
            await service.cancel(turn.id)
            await late.wait()
            assert store.get_turn(turn.id).status == TurnStatus.CANCELLED
            assert store.get_turn(turn.id).cancel_requested
            assert all("late" not in m.content for m in store.list_messages(first.id).items)
            await service.cancel(turn.id)
            assert len([e for e in store.list_events(first.id) if e.kind == "turn.cancelled"]) == 1
            for pending in queued:
                await service.cancel(pending.id)
        finally:
            await service.close()

    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        asyncio.run(asyncio.wait_for(scenario(store), timeout=10))


def test_clarification_requires_current_request_and_revision(tmp_path):
    async def scenario(store):
        calls = []

        def prepare(profile_id, fixed=None):
            async def answer(messages):
                calls.append(messages[-1].content)
                if messages[-1].content == "help":
                    yield Clarification("Which group?")
                else:
                    yield "confirmed"

            return PreparedChat(fixed or snapshot(), answer)

        service = TurnService(store, prepare)
        await service.start()
        try:
            c = chat(store)
            turn = await service.submit(c.id, uuid4(), "help", uuid4())
            await until(lambda: store.get_turn(turn.id).status == TurnStatus.WAITING_USER)
            waiting = store.get_turn(turn.id).pending_input
            assert waiting.question == "Which group?"
            with pytest.raises(ValueError, match="TURN_BUSY"):
                await service.submit(c.id, uuid4(), "other", uuid4())
            with pytest.raises(ValueError, match="INPUT_RESPONSE_CONFLICT"):
                await service.respond(turn.id, uuid4(), waiting.revision, "clarify", "AD")
            with pytest.raises(ValueError, match="INPUT_RESPONSE_CONFLICT"):
                await service.respond(
                    turn.id, waiting.request_id, waiting.revision + 1, "clarify", "AD"
                )
            await service.respond(turn.id, waiting.request_id, waiting.revision, "clarify", "AD")
            await until(lambda: store.get_turn(turn.id).status == TurnStatus.COMPLETED)
            with pytest.raises(ValueError, match="INPUT_RESPONSE_CONFLICT"):
                await service.respond(
                    turn.id, waiting.request_id, waiting.revision, "clarify", "AD"
                )
            assert calls == ["help", "AD"]
        finally:
            await service.close()

    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        asyncio.run(asyncio.wait_for(scenario(store), timeout=10))


def test_restart_interrupts_unfinished_once_without_replaying_model(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        c = chat(store)
        turn = store.begin_turn(c.id, uuid4(), "hello", snapshot())
        store.update_turn(turn.id, TurnStatus.RUNNING)
        partial = store.append_message(c.id, turn.id, "assistant", "partial", partial=True)

    async def restart(store):
        def forbidden(*_):
            raise AssertionError("must not replay")

        service = TurnService(store, forbidden)
        await service.start()
        await service.close()

    for _ in range(2):
        with WorkbenchStore(path) as store:
            asyncio.run(restart(store))
            assert store.get_turn(turn.id).error_code == "TURN_INTERRUPTED"
            assert store.get_turn(turn.id).status == TurnStatus.FAILED
            assert partial in store.list_messages(c.id).items
            assert len([e for e in store.list_events(c.id) if e.kind == "turn.failed"]) == 1


def test_sse_replay_heartbeat_and_disconnect_leave_turn_running(tmp_path):
    async def scenario(store):
        c = chat(store)
        turn = store.begin_turn(c.id, uuid4(), "hello", None)
        for i in range(105):
            store.append_event(c.id, turn.id, "message.delta", {"text": str(i)})
        now = [0.0]

        async def tick(seconds):
            now[0] += seconds

        stream = stream_events(store, c.id, after=3, clock=lambda: now[0], pause=tick)
        frames = [await anext(stream) for _ in range(103)]
        assert [int(f.splitlines()[0][4:]) for f in frames] == list(range(4, 107))
        heartbeat = await anext(stream)
        assert heartbeat.startswith(":") and now[0] >= 15
        await stream.aclose()
        assert store.get_turn(turn.id).status == TurnStatus.QUEUED
        assert len(store.list_events(c.id, after=6, limit=100)) == 100
        replay = stream_events(store, c.id, after=105)
        assert (await anext(replay)).startswith("id: 106\n")
        await replay.aclose()

    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        asyncio.run(asyncio.wait_for(scenario(store), timeout=10))


def test_completion_event_failure_rolls_back_message_and_terminal_state(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        c = chat(store)
        turn = store.begin_turn(c.id, uuid4(), "hello", None)
        store.update_turn(turn.id, TurnStatus.RUNNING)
        store.append_delta(turn.id, "partial")
        before = store.list_events(c.id)
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TRIGGER reject_completion BEFORE INSERT ON events
                WHEN json_extract(NEW.record, '$.kind')='turn.completed'
                BEGIN SELECT RAISE(ABORT, 'injected completion failure'); END""")
        with pytest.raises(sqlite3.IntegrityError):
            store.complete_output(turn.id)
        assert store.get_turn(turn.id).status == TurnStatus.RUNNING
        assert store.list_messages(c.id).items[0].partial
        assert store.list_events(c.id) == before


def test_default_driver_freezes_config_and_excludes_private_reasoning(
    tmp_path, monkeypatch, caplog
):
    from bioagent.models.profiles import ModelProfile

    profile = ModelProfile(
        id=uuid4(), label="test", credential_ref="internal", **snapshot().model_dump()
    )
    profiles = Mock()
    profiles.request_config.return_value = (profile, SecretStr("synthetic-not-for-db"))
    prompt = []

    async def output(messages):
        prompt.extend(messages)
        yield SimpleNamespace(
            content=[
                {"type": "reasoning", "text": "private-reasoning"},
                {"type": "text", "text": "public"},
            ]
        )

    constructor = Mock(return_value=SimpleNamespace(astream=output))
    monkeypatch.setattr("bioagent.workbench.turns.ChatOllama", constructor)
    prepared = ConfiguredChatFactory(profiles)(profile.id, None)
    profiles.request_config.return_value = (profile.model_copy(update={"model": "changed"}), None)

    async def run(store):
        c = chat(store)
        service = TurnService(store, lambda *_: prepared)
        await service.start()
        try:
            turn = await service.submit(c.id, uuid4(), "hello", profile.id)
            await until(lambda: store.get_turn(turn.id).status == TurnStatus.COMPLETED)
            assert store.get_turn(turn.id).model_snapshot.model == "mock-a"
            assert store.list_messages(c.id).items[0].content == "public"
        finally:
            await service.close()

    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        asyncio.run(asyncio.wait_for(run(store), timeout=10))
    assert constructor.call_args.kwargs["model"] == "mock-a"
    assert all("private-reasoning" not in message.content for message in prompt)
    assert b"synthetic-not-for-db" not in path.read_bytes()
    assert b"private-reasoning" not in path.read_bytes()
    assert "synthetic-not-for-db" not in caplog.text


def test_retry_after_service_restart_does_not_prepare_or_reinvoke(tmp_path):
    async def run(path):
        request_id, profile_id = uuid4(), uuid4()

        async def answer(_):
            yield "done"

        with WorkbenchStore(path) as store:
            c = chat(store)
            service = TurnService(store, lambda *_: PreparedChat(snapshot(), answer))
            await service.start()
            turn = await service.submit(c.id, request_id, "hello", profile_id)
            await until(lambda: store.get_turn(turn.id).status == TurnStatus.COMPLETED)
            await service.close()
        with WorkbenchStore(path) as store:
            forbidden = Mock(side_effect=AssertionError("must not prepare"))
            service = TurnService(store, forbidden)
            await service.start()
            try:
                duplicate = await service.submit(c.id, request_id, "hello", profile_id)
                assert duplicate.id == turn.id and duplicate.status == TurnStatus.COMPLETED
                forbidden.assert_not_called()
            finally:
                await service.close()

    asyncio.run(asyncio.wait_for(run(tmp_path / "wb.sqlite"), timeout=10))


def test_waiting_closes_driver_stream_without_waiting_for_garbage_collection(tmp_path):
    async def run(store):
        retained, closed = [], []

        async def answer(_):
            try:
                yield Clarification("question")
            finally:
                closed.append(True)

        def stream(messages):
            opened = answer(messages)
            retained.append(opened)
            return opened

        service = TurnService(store, lambda *_: PreparedChat(snapshot(), stream))
        await service.start()
        try:
            c = chat(store)
            turn = await service.submit(c.id, uuid4(), "hello", uuid4())
            await until(
                lambda: (
                    store.get_turn(turn.id).status == TurnStatus.WAITING_USER
                    and turn.id not in service._running
                )
            )
            assert closed == [True]
        finally:
            await service.close()
            for opened in retained:
                await opened.aclose()

    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        asyncio.run(asyncio.wait_for(run(store), timeout=10))
