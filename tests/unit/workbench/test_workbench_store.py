import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import ValidationError

from bioagent.config import Settings
from bioagent.workbench.models import TurnStatus
from bioagent.workbench.store import WorkbenchStore


def make_chat(store):
    project = store.create_project("RNA 项目")
    return store.create_conversation(project.id, "第一次分析")


def begin(store, chat, request_id=None, **kwargs):
    return store.begin_turn(chat.id, request_id or uuid4(), "检查数据", None, **kwargs)


def test_request_is_idempotent_after_reopen(tmp_path):
    path = tmp_path / "workbench.sqlite"
    store = WorkbenchStore(path)
    chat = make_chat(store)
    request_id = uuid4()
    first = begin(store, chat, request_id)
    store.close()
    with WorkbenchStore(path) as reopened:
        assert begin(reopened, chat, request_id) == first
        assert len(reopened.list_messages(chat.id).items) == 1
        events = reopened.list_events(chat.id)
        assert len(events) == 1
        assert events[0].payload["message_id"] == str(reopened.list_messages(chat.id).items[0].id)


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_requests_across_connections(tmp_path, same_request):
    path = tmp_path / "workbench.sqlite"
    with WorkbenchStore(path) as store:
        chat = make_chat(store)
    gate = Barrier(6)
    request_id = uuid4()

    def submit(_):
        with WorkbenchStore(path) as store:
            gate.wait(timeout=10)
            try:
                return begin(store, chat, request_id if same_request else uuid4()).id
            except ValueError as exc:
                return str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))
    if same_request:
        assert len(set(results)) == 1
        assert results[0] != "TURN_BUSY"
    else:
        assert results.count("TURN_BUSY") == 5
    with WorkbenchStore(path) as store:
        assert len(store.list_messages(chat.id).items) == 1
        assert len(store.list_events(chat.id)) == 1


def test_conflict_precedes_busy_and_other_conversation_can_start(tmp_path):
    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        chat = make_chat(store)
        first = begin(store, chat)
        with pytest.raises(ValueError, match="REQUEST_ID_CONFLICT"):
            store.begin_turn(chat.id, first.client_request_id, "不同内容", None)
        with pytest.raises(ValueError, match="REQUEST_ID_CONFLICT"):
            store.begin_turn(
                chat.id, first.client_request_id, "检查数据", None, dataset_ids=(uuid4(),)
            )
        store.update_turn(first.id, TurnStatus.RUNNING)
        store.update_turn(first.id, TurnStatus.WAITING_USER)
        with pytest.raises(ValueError, match="TURN_BUSY"):
            begin(store, chat)
        assert begin(store, make_chat(store)).status == TurnStatus.QUEUED
        store.update_turn(first.id, TurnStatus.CANCELLED)
        assert begin(store, chat).id != first.id
        assert begin(store, chat, first.client_request_id).status == TurnStatus.CANCELLED
        with pytest.raises(ValueError, match="INVALID_TURN_TRANSITION"):
            store.update_turn(first.id, TurnStatus.RUNNING)


def test_failure_rolls_back_turn_message_event_and_counter(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        chat = make_chat(store)
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TRIGGER reject_event BEFORE INSERT ON events
                          BEGIN SELECT RAISE(ABORT, 'injected event failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="injected event failure"):
            begin(store, chat)
        assert store.list_messages(chat.id).items == ()
        assert store.list_events(chat.id) == ()
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
            db.execute("DROP TRIGGER reject_event")
        begin(store, chat)
        assert store.list_events(chat.id)[0].seq == 1


def test_event_concurrency_replay_and_ownership(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        chat = make_chat(store)
        turn = begin(store, chat)
        other_chat = make_chat(store)
        other_turn = begin(store, other_chat)
        with pytest.raises(ValueError, match="TURN_NOT_FOUND"):
            store.append_event(chat.id, other_turn.id, "message.delta", {"text": "x"})

    def append(i):
        with WorkbenchStore(path) as store:
            return store.append_event(chat.id, turn.id, "message.delta", {"text": str(i)})

    with ThreadPoolExecutor(max_workers=4) as pool:
        events = list(pool.map(append, range(20)))
    with WorkbenchStore(path) as store:
        assert sorted(e.seq for e in events) == list(range(2, 22))
        replay = []
        after = 0
        while batch := store.list_events(chat.id, after=after, limit=4):
            replay.extend(batch)
            after = batch[-1].seq
        assert [e.seq for e in replay] == list(range(1, 22))
        assert len(store.list_events(other_chat.id)) == 1


def test_rename_archive_preserves_evidence_and_partial_messages(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        chat = make_chat(store)
        turn = begin(store, chat)
        partial = store.append_message(chat.id, turn.id, "assistant", "正在检查", partial=True)
        project = store.update_project(chat.project_id, title="新项目", archived=True)
        changed = store.update_conversation(chat.id, title="新对话", archived=True)
        assert project.archived and changed.archived
        assert changed.updated_at >= chat.updated_at
        assert store.list_projects().items == (project,)
        assert store.list_conversations(project.id).items == (changed,)
        with pytest.raises(ValidationError):
            changed.title = "cannot mutate"
    with WorkbenchStore(path) as reopened:
        assert partial in reopened.list_messages(chat.id).items
        assert reopened.get_turn(turn.id) == turn
        assert reopened.list_events(chat.id)[-1].kind == "message.delta"


def test_pagination_default_maximum_ties_and_cursor_scope(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        projects = [store.create_project(str(i)) for i in range(105)]
        # Equal timestamps force the ID tie-breaker to do real work.
        with sqlite3.connect(path) as db:
            db.execute("UPDATE projects SET updated_at = ?", (projects[0].updated_at.isoformat(),))
        first = store.list_projects()
        assert len(first.items) == 50 and first.next_cursor
        second = store.list_projects(cursor=first.next_cursor)
        third = store.list_projects(cursor=second.next_cursor)
        assert len(third.items) == 5 and third.next_cursor is None
        ids = [p.id for p in first.items + second.items + third.items]
        assert ids == sorted((p.id for p in projects), reverse=True)
        assert len(store.list_projects(limit=100).items) == 100
        chat = store.create_conversation(projects[0].id, "a")
        for i in range(4):
            store.create_conversation(projects[0].id, str(i))
        chats = store.list_conversations(projects[0].id, limit=2)
        assert chats.next_cursor
        assert len(store.list_conversations(projects[0].id, cursor=chats.next_cursor).items) == 3
        turn = begin(store, chat)
        for i in range(4):
            store.append_message(chat.id, turn.id, "assistant", str(i))
        messages = store.list_messages(chat.id, limit=2)
        assert messages.next_cursor
        assert len(store.list_messages(chat.id, cursor=messages.next_cursor).items) == 3
        with pytest.raises(ValueError, match="INVALID_CURSOR"):
            store.list_messages(chat.id, cursor=first.next_cursor)
        with pytest.raises(ValueError, match="INVALID_CURSOR"):
            store.list_projects(cursor="invalid")
        for invalid in (0, -1, 101, True):
            with pytest.raises(ValueError, match="INVALID_LIMIT"):
                store.list_projects(limit=invalid)
            with pytest.raises(ValueError, match="INVALID_LIMIT"):
                store.list_events(chat.id, limit=invalid)
        with pytest.raises(ValueError, match="INVALID_CURSOR"):
            store.list_events(chat.id, after=-1)


def test_foreign_keys_invalid_ids_and_newer_schema_rejected(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        with pytest.raises(ValueError, match="PROJECT_NOT_FOUND"):
            store.create_conversation(uuid4(), "bad")
        with pytest.raises(ValueError):
            store.create_conversation("../bad", "bad")
        with pytest.raises(ValueError, match="CONVERSATION_NOT_FOUND"):
            store.begin_turn(uuid4(), uuid4(), "bad", None)
        chat = make_chat(store)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE conversations SET project_id = ?", (str(uuid4()),))
    with pytest.raises(ValueError, match="WORKBENCH_FOREIGN_KEY_INVALID"):
        WorkbenchStore(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE conversations SET project_id = ?", (str(chat.project_id),))
        db.execute("UPDATE schema_version SET version = 999")
    with pytest.raises(ValueError, match="WORKBENCH_SCHEMA_TOO_NEW"):
        WorkbenchStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 999


def test_unversioned_database_is_not_adopted_or_modified(tmp_path):
    path = tmp_path / "checkpoint.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE checkpoints (value TEXT)")
        db.execute("INSERT INTO checkpoints VALUES ('keep')")
    with pytest.raises(ValueError, match="WORKBENCH_SCHEMA_INVALID"):
        WorkbenchStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM checkpoints").fetchall() == [("keep",)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("checkpoints",)
        ]


def test_message_limits_snapshot_validation_and_config(tmp_path):
    assert Settings(_env_file=None).workbench_db == Path("data/workbench.sqlite")
    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        chat = make_chat(store)
        with pytest.raises(ValueError):
            store.begin_turn(chat.id, uuid4(), "中" * 5462, None)
        with pytest.raises(ValueError):
            store.begin_turn(chat.id, uuid4(), "text", {"credential_ref": "not-allowed"})
        with pytest.raises(ValueError):
            store.create_project("   ")
        snapshot = dict(
            provider="ollama",
            model="local",
            base_url="http://127.0.0.1:11434",
            revision=1,
            structured_method="function_calling",
            thinking="default",
        )
        turn = store.begin_turn(chat.id, uuid4(), "中" * 5461, snapshot)
        snapshot["model"] = "changed"
        assert turn.model_snapshot.model == "local"
        with pytest.raises(ValidationError):
            turn.model_snapshot.model = "changed"
        with pytest.raises(ValueError, match="REQUEST_ID_CONFLICT"):
            store.begin_turn(chat.id, turn.client_request_id, "中" * 5461, snapshot)
        with pytest.raises(ValueError):
            store.append_event(chat.id, turn.id, "made.up", {})
        with pytest.raises(ValueError):
            store.append_event(chat.id, turn.id, "message.delta", {"number": float("nan")})


def test_new_activity_updates_conversation_and_project_order(tmp_path):
    with WorkbenchStore(tmp_path / "wb.sqlite") as store:
        old = make_chat(store)
        recent = make_chat(store)
        assert store.list_projects().items[0].id == recent.project_id
        sibling = store.create_conversation(old.project_id, "newer chat")
        assert store.list_conversations(old.project_id).items[0].id == sibling.id
        begin(store, old)
        assert store.list_projects().items[0].id == old.project_id
        assert store.list_conversations(old.project_id).items[0].id == old.id


def test_version_zero_migrates_and_failed_migration_is_atomic(tmp_path):
    path = tmp_path / "wb.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        db.execute("INSERT INTO schema_version VALUES (0)")
    with WorkbenchStore(path) as store:
        project = store.create_project("migrated")
    with WorkbenchStore(path) as store:
        assert store.list_projects().items == (project,)
    broken = tmp_path / "broken.sqlite"
    with sqlite3.connect(broken) as db:
        db.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        db.execute("INSERT INTO schema_version VALUES (0)")
        db.execute("CREATE TABLE turns (keep TEXT)")
    with pytest.raises(sqlite3.OperationalError):
        WorkbenchStore(broken)
    with sqlite3.connect(broken) as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 0
        assert db.execute("SELECT name FROM sqlite_master WHERE name='projects'").fetchone() is None


def test_missing_schema_objects_are_rejected_without_repair(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path):
        pass
    with sqlite3.connect(path) as db:
        db.execute("DROP INDEX one_active_turn")
    with pytest.raises(ValueError, match="WORKBENCH_SCHEMA_INVALID"):
        WorkbenchStore(path)


def test_one_store_supports_worker_threads_and_database_enforces_ownership(tmp_path):
    path = tmp_path / "wb.sqlite"
    with WorkbenchStore(path) as store:
        chat = make_chat(store)
        request_id = uuid4()
        with ThreadPoolExecutor(max_workers=4) as pool:
            turns = list(pool.map(lambda _: begin(store, chat, request_id), range(8)))
        assert len({turn.id for turn in turns}) == 1
        other = make_chat(store)
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA foreign_keys=ON")
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                db.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), str(other.id), str(turns[0].id), "now", "{}"),
                )
