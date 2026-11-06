"""Short SQLite transactions, independent of checkpoints and scientific artifacts."""

import base64
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Literal, Self
from uuid import UUID, uuid4

from bioagent.workbench.models import (
    Conversation,
    Event,
    EventKind,
    Message,
    Page,
    PendingInput,
    Project,
    Record,
    Turn,
    TurnModelSnapshot,
    TurnStatus,
    WorkbenchError,
)

_UNSET = object()

# Migrations run one statement at a time: executescript would implicitly commit.
_MIGRATIONS = (
    (
        """CREATE TABLE projects (
            id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, record TEXT NOT NULL)""",
        """CREATE TABLE conversations (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            updated_at TEXT NOT NULL, record TEXT NOT NULL, next_seq INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE turns (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
            client_request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN
              ('QUEUED','RUNNING','WAITING_USER','COMPLETED','FAILED','CANCELLED')),
            record TEXT NOT NULL, UNIQUE(conversation_id, id))""",
        "CREATE UNIQUE INDEX turn_request_once ON turns(conversation_id, client_request_id)",
        """CREATE UNIQUE INDEX one_active_turn ON turns(conversation_id)
            WHERE status IN ('QUEUED','RUNNING','WAITING_USER')""",
        """CREATE TABLE messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
            updated_at TEXT NOT NULL, record TEXT NOT NULL,
            FOREIGN KEY(conversation_id, turn_id) REFERENCES turns(conversation_id, id))""",
        """CREATE TABLE events (
            conversation_id TEXT NOT NULL, seq INTEGER NOT NULL CHECK(seq > 0),
            turn_id TEXT NOT NULL, record TEXT NOT NULL,
            FOREIGN KEY(conversation_id, turn_id) REFERENCES turns(conversation_id, id))""",
        "CREATE UNIQUE INDEX event_sequence ON events(conversation_id, seq)",
        "CREATE INDEX project_page ON projects(updated_at DESC, id DESC)",
        "CREATE INDEX conversation_page ON conversations(project_id, updated_at DESC, id DESC)",
        "CREATE INDEX message_page ON messages(conversation_id, updated_at DESC, id DESC)",
    ),
)
_TRANSITIONS = {
    TurnStatus.QUEUED: {TurnStatus.RUNNING, TurnStatus.FAILED, TurnStatus.CANCELLED},
    TurnStatus.RUNNING: {
        TurnStatus.WAITING_USER,
        TurnStatus.COMPLETED,
        TurnStatus.FAILED,
        TurnStatus.CANCELLED,
    },
    TurnStatus.WAITING_USER: {
        TurnStatus.QUEUED,
        TurnStatus.RUNNING,
        TurnStatus.COMPLETED,
        TurnStatus.FAILED,
        TurnStatus.CANCELLED,
    },
}


def _id(value: UUID | str) -> str:
    return str(UUID(str(value)))


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("INVALID_LIMIT")


class WorkbenchStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(path, timeout=10, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._migrate()
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        # The instance lock also protects one connection across HTTP worker threads;
        # BEGIN IMMEDIATE + unique indexes protect separate connections/processes.
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def _migrate(self) -> None:
        with self._transaction() as db:
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if "schema_version" not in tables:
                if tables:
                    raise ValueError("WORKBENCH_SCHEMA_INVALID")
                db.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
                db.execute("INSERT INTO schema_version VALUES (0)")
            versions = db.execute("SELECT version FROM schema_version").fetchall()
            if len(versions) != 1 or type(versions[0][0]) is not int or versions[0][0] < 0:
                raise ValueError("WORKBENCH_SCHEMA_INVALID")
            version = versions[0][0]
            if version > len(_MIGRATIONS):
                raise ValueError("WORKBENCH_SCHEMA_TOO_NEW")
            for index in range(version, len(_MIGRATIONS)):
                for statement in _MIGRATIONS[index]:
                    db.execute(statement)
                db.execute("UPDATE schema_version SET version = ?", (index + 1,))
            required = {
                "schema_version",
                "projects",
                "conversations",
                "turns",
                "messages",
                "events",
                "turn_request_once",
                "one_active_turn",
                "event_sequence",
            }
            objects = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            if not required <= objects:
                raise ValueError("WORKBENCH_SCHEMA_INVALID")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("WORKBENCH_FOREIGN_KEY_INVALID")

    def _get[T: Record](
        self,
        db: sqlite3.Connection,
        table: str,
        identity: UUID | str,
        model: type[T],
        code: str,
    ) -> T:
        # Table identifiers are internal constants, never caller-supplied strings.
        row = db.execute(f"SELECT record FROM {table} WHERE id = ?", (_id(identity),)).fetchone()
        if row is None:
            raise ValueError(code)
        return model.model_validate_json(row["record"])

    def create_project(self, title: str) -> Project:
        now = datetime.now(UTC)
        project = Project(id=uuid4(), title=title, created_at=now, updated_at=now)
        with self._transaction() as db:
            db.execute(
                "INSERT INTO projects VALUES (?, ?, ?)",
                (str(project.id), now.isoformat(), project.model_dump_json()),
            )
        return project

    def create_conversation(self, project_id: UUID | str, title: str) -> Conversation:
        now = datetime.now(UTC)
        chat = Conversation(
            id=uuid4(),
            project_id=UUID(_id(project_id)),
            title=title,
            created_at=now,
            updated_at=now,
        )
        with self._transaction() as db:
            self._get(db, "projects", project_id, Project, "PROJECT_NOT_FOUND")
            db.execute(
                """INSERT INTO conversations (id, project_id, updated_at, record)
                          VALUES (?, ?, ?, ?)""",
                (str(chat.id), str(chat.project_id), now.isoformat(), chat.model_dump_json()),
            )
        return chat

    def _update[T: Project](
        self,
        table: str,
        identity: UUID | str,
        model: type[T],
        code: str,
        title: str | None,
        archived: bool | None,
        selected_profile_id: UUID | None = None,
        select_profile: bool = False,
    ) -> T:
        with self._transaction() as db:
            original = self._get(db, table, identity, model, code)
            data = original.model_dump()
            data["updated_at"] = datetime.now(UTC)
            if title is not None:
                data["title"] = title
            if archived is not None:
                data["archived"] = archived
            if select_profile:
                data["selected_profile_id"] = selected_profile_id
            changed = model.model_validate(data)
            db.execute(
                f"UPDATE {table} SET updated_at = ?, record = ? WHERE id = ?",
                (changed.updated_at.isoformat(), changed.model_dump_json(), _id(identity)),
            )
        return changed

    def update_project(
        self,
        project_id: UUID | str,
        *,
        title: str | None = None,
        archived: bool | None = None,
    ) -> Project:
        return self._update("projects", project_id, Project, "PROJECT_NOT_FOUND", title, archived)

    def update_conversation(
        self,
        conversation_id: UUID | str,
        *,
        title: str | None = None,
        archived: bool | None = None,
        selected_profile_id: UUID | None = None,
        select_profile: bool = False,
    ) -> Conversation:
        return self._update(
            "conversations",
            conversation_id,
            Conversation,
            "CONVERSATION_NOT_FOUND",
            title,
            archived,
            selected_profile_id,
            select_profile,
        )

    def begin_turn(
        self,
        conversation_id: UUID | str,
        client_request_id: UUID | str,
        text: str,
        model_snapshot: TurnModelSnapshot | Mapping[str, object] | None,
        *,
        dataset_ids: tuple[UUID, ...] = (),
        profile_id: UUID | None = None,
        requested_profile_id: UUID | None = None,
    ) -> Turn:
        now = datetime.now(UTC)
        snapshot = (
            TurnModelSnapshot.model_validate(model_snapshot) if model_snapshot is not None else None
        )
        turn = Turn(
            id=uuid4(),
            conversation_id=UUID(_id(conversation_id)),
            client_request_id=UUID(_id(client_request_id)),
            model_snapshot=snapshot,
            profile_id=profile_id,
            requested_profile_id=requested_profile_id,
            created_at=now,
            updated_at=now,
        )
        message = Message(
            id=uuid4(),
            conversation_id=turn.conversation_id,
            turn_id=turn.id,
            role="user",
            content=text,
            dataset_ids=dataset_ids,
            created_at=now,
            updated_at=now,
        )
        if not text.strip():
            raise ValueError("MESSAGE_REQUIRED")
        fingerprint = sha256(
            _json(
                {
                    "text": text,
                    "dataset_ids": [str(value) for value in message.dataset_ids],
                    "model_snapshot": snapshot.model_dump(mode="json") if snapshot else None,
                }
            ).encode("utf-8")
        ).hexdigest()
        with self._transaction() as db:
            self._get(db, "conversations", conversation_id, Conversation, "CONVERSATION_NOT_FOUND")
            duplicate = db.execute(
                "SELECT record, request_hash FROM turns "
                "WHERE conversation_id=? AND client_request_id=?",
                (_id(conversation_id), _id(client_request_id)),
            ).fetchone()
            if duplicate is not None:
                if duplicate["request_hash"] != fingerprint:
                    raise ValueError("REQUEST_ID_CONFLICT")
                return Turn.model_validate_json(duplicate["record"])
            active = db.execute(
                """SELECT 1 FROM turns WHERE conversation_id=?
                                   AND status IN ('QUEUED','RUNNING','WAITING_USER')""",
                (_id(conversation_id),),
            ).fetchone()
            if active is not None:
                raise ValueError("TURN_BUSY")
            db.execute(
                "INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(turn.id),
                    str(turn.conversation_id),
                    str(turn.client_request_id),
                    fingerprint,
                    turn.status.value,
                    turn.model_dump_json(),
                ),
            )
            self._insert_message(db, message)
        return turn

    def _owned_turn(
        self,
        db: sqlite3.Connection,
        conversation_id: UUID | str,
        turn_id: UUID | str,
    ) -> Turn:
        turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
        if str(turn.conversation_id) != _id(conversation_id):
            raise ValueError("TURN_NOT_FOUND")
        return turn

    def get_turn(self, turn_id: UUID | str) -> Turn:
        with self._lock:
            return self._get(self._db, "turns", turn_id, Turn, "TURN_NOT_FOUND")

    def set_run_id(self, turn_id: UUID | str, run_id: UUID) -> Turn:
        with self._transaction() as db:
            turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            data = {**turn.model_dump(), "run_id": run_id, "updated_at": datetime.now(UTC)}
            changed = Turn.model_validate(data)
            db.execute(
                "UPDATE turns SET record=? WHERE id=?",
                (changed.model_dump_json(), str(changed.id)),
            )
            return changed

    def set_geo_source(self, conversation_id: UUID | str, source_id: UUID) -> Conversation:
        with self._transaction() as db:
            original = self._get(
                db, "conversations", conversation_id, Conversation, "CONVERSATION_NOT_FOUND"
            )
            changed = Conversation.model_validate(
                {
                    **original.model_dump(),
                    "geo_source_id": source_id,
                    "updated_at": datetime.now(UTC),
                }
            )
            db.execute(
                "UPDATE conversations SET updated_at=?, record=? WHERE id=?",
                (changed.updated_at.isoformat(), changed.model_dump_json(), str(changed.id)),
            )
            return changed

    def find_run_turn(self, run_id: UUID | str) -> Turn | None:
        with self._lock:
            rows = self._db.execute("SELECT record FROM turns").fetchall()
        for row in rows:
            turn = Turn.model_validate_json(row[0])
            if turn.run_id == UUID(_id(run_id)):
                return turn
        return None

    def finish_run_turn(
        self, run_id: UUID | str, *, success: bool, error_code: str | None = None
    ) -> Turn | None:
        with self._transaction() as db:
            rows = db.execute("SELECT record FROM turns").fetchall()
            for row in rows:
                turn = Turn.model_validate_json(row[0])
                if turn.run_id != UUID(_id(run_id)):
                    continue
                if turn.status not in {TurnStatus.WAITING_USER, TurnStatus.RUNNING}:
                    return turn
                return self._change_turn(
                    db,
                    turn,
                    TurnStatus.COMPLETED if success else TurnStatus.FAILED,
                    error_code=None if success else error_code,
                    pending_input=None,
                )
        return None

    def update_turn(self, turn_id: UUID | str, status: TurnStatus) -> Turn:
        """Persist a lifecycle change and its terminal event atomically; never revive terminals."""
        status = TurnStatus(status)
        with self._transaction() as db:
            original = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            return self._change_turn(db, original, status)

    def update_turn_progress(
        self,
        turn_id: UUID | str,
        *,
        action_count: int | None = None,
        active_seconds: float | None = None,
        pending_tool_call: dict[str, object] | None | object = _UNSET,
    ) -> Turn:
        """Persist bounded execution counters without emitting a lifecycle event."""

        with self._transaction() as db:
            original = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            data = original.model_dump()
            if action_count is not None:
                data["action_count"] = action_count
            if active_seconds is not None:
                data["active_seconds"] = active_seconds
            if pending_tool_call is not _UNSET:
                data["pending_tool_call"] = pending_tool_call
            data["updated_at"] = datetime.now(UTC)
            changed = Turn.model_validate(data)
            db.execute(
                "UPDATE turns SET record=? WHERE id=?",
                (changed.model_dump_json(), str(changed.id)),
            )
            return changed

    def _change_turn(
        self, db: sqlite3.Connection, original: Turn, status: TurnStatus, **updates: object
    ) -> Turn:
        if original.status == status:
            return original
        if status not in _TRANSITIONS.get(original.status, set()):
            raise WorkbenchError("INVALID_TURN_TRANSITION")
        data = original.model_dump()
        data.update(updates)
        data.update(status=status, updated_at=datetime.now(UTC))
        turn = Turn.model_validate(data)
        db.execute(
            "UPDATE turns SET status=?, record=? WHERE id=?",
            (status.value, turn.model_dump_json(), str(turn.id)),
        )
        kinds: dict[TurnStatus, EventKind] = {
            TurnStatus.RUNNING: "turn.started",
            TurnStatus.COMPLETED: "turn.completed",
            TurnStatus.FAILED: "turn.failed",
            TurnStatus.CANCELLED: "turn.cancelled",
        }
        if status in kinds:
            self._insert_event(
                db,
                turn.conversation_id,
                turn.id,
                kinds[status],
                {"status": status.value, "error_code": turn.error_code},
            )
        return turn

    def get_conversation(self, conversation_id: UUID | str) -> Conversation:
        with self._lock:
            return self._get(
                self._db, "conversations", conversation_id, Conversation, "CONVERSATION_NOT_FOUND"
            )

    def find_request(self, conversation_id: UUID | str, request_id: UUID) -> Turn | None:
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM turns WHERE conversation_id=? AND client_request_id=?",
                (_id(conversation_id), str(request_id)),
            ).fetchone()
        return Turn.model_validate_json(row[0]) if row is not None else None

    def verify_request(
        self, turn: Turn, text: str, profile_id: UUID | None, dataset_ids: tuple[UUID, ...]
    ) -> None:
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM messages WHERE turn_id=? ORDER BY rowid LIMIT 1",
                (str(turn.id),),
            ).fetchone()
        message = Message.model_validate_json(row[0]) if row is not None else None
        if (
            message is None
            or message.content != text
            or message.dataset_ids != dataset_ids
            or turn.requested_profile_id != profile_id
        ):
            raise WorkbenchError("REQUEST_ID_CONFLICT")

    def active_turn(self, conversation_id: UUID) -> Turn | None:
        with self._lock:
            row = self._db.execute(
                """SELECT record FROM turns WHERE conversation_id=?
                                   AND status IN ('QUEUED','RUNNING','WAITING_USER')""",
                (str(conversation_id),),
            ).fetchone()
        return Turn.model_validate_json(row[0]) if row else None

    def _partial_message(self, db: sqlite3.Connection, turn: Turn) -> Message | None:
        row = db.execute(
            """SELECT record FROM messages WHERE turn_id=?
                         AND json_extract(record, '$.role')='assistant'
                         AND json_extract(record, '$.partial')=1 ORDER BY rowid DESC LIMIT 1""",
            (str(turn.id),),
        ).fetchone()
        return Message.model_validate_json(row[0]) if row else None

    def append_delta(self, turn_id: UUID, text: str) -> bool:
        with self._transaction() as db:
            turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            if turn.status != TurnStatus.RUNNING or turn.cancel_requested:
                return False
            original = self._partial_message(db, turn)
            now = datetime.now(UTC)
            if original is None:
                message = Message(
                    id=uuid4(),
                    conversation_id=turn.conversation_id,
                    turn_id=turn.id,
                    role="assistant",
                    content=text,
                    partial=True,
                    created_at=now,
                    updated_at=now,
                )
                self._insert_message(db, message)
            else:
                message = Message.model_validate(
                    {**original.model_dump(), "content": original.content + text, "updated_at": now}
                )
                db.execute(
                    "UPDATE messages SET record=?, updated_at=? WHERE id=?",
                    (message.model_dump_json(), now.isoformat(), str(message.id)),
                )
                self._insert_event(
                    db,
                    turn.conversation_id,
                    turn.id,
                    "message.delta",
                    {
                        "message_id": str(message.id),
                        "text": text,
                        "role": "assistant",
                        "partial": True,
                    },
                )
            return True

    def _finish_message(self, db: sqlite3.Connection, turn: Turn) -> None:
        original = self._partial_message(db, turn)
        if original is None:
            return
        message = Message.model_validate(
            {**original.model_dump(), "partial": False, "updated_at": datetime.now(UTC)}
        )
        db.execute(
            "UPDATE messages SET record=?, updated_at=? WHERE id=?",
            (message.model_dump_json(), message.updated_at.isoformat(), str(message.id)),
        )
        self._insert_event(
            db,
            turn.conversation_id,
            turn.id,
            "message.completed",
            {
                "message_id": str(message.id),
                "text": message.content,
                "role": "assistant",
                "partial": False,
            },
        )

    def complete_output(self, turn_id: UUID) -> Turn:
        with self._transaction() as db:
            turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            if turn.status != TurnStatus.RUNNING:
                return turn
            self._finish_message(db, turn)
            return self._change_turn(db, turn, TurnStatus.COMPLETED)

    def fail_turn(self, turn_id: UUID, code: str) -> Turn:
        with self._transaction() as db:
            turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            if turn.status not in _TRANSITIONS:
                return turn
            return self._change_turn(
                db, turn, TurnStatus.FAILED, error_code=code, pending_input=None
            )

    def cancel_turn(self, turn_id: UUID) -> Turn:
        with self._transaction() as db:
            turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            if turn.status not in _TRANSITIONS:
                return turn
            return self._change_turn(
                db, turn, TurnStatus.CANCELLED, cancel_requested=True, pending_input=None
            )

    def interrupt_unfinished(self) -> None:
        with self._transaction() as db:
            rows = db.execute(
                "SELECT record FROM turns WHERE status IN ('QUEUED','RUNNING','WAITING_USER')"
            ).fetchall()
            for row in rows:
                turn = Turn.model_validate_json(row[0])
                self._change_turn(
                    db, turn, TurnStatus.FAILED, error_code="TURN_INTERRUPTED", pending_input=None
                )

    def require_input(self, turn_id: UUID, question: str) -> Turn:
        with self._transaction() as db:
            turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            if turn.status != TurnStatus.RUNNING:
                return turn
            pending = PendingInput(
                request_id=uuid4(), revision=turn.input_revision + 1, question=question
            )
            self._finish_message(db, turn)
            now = datetime.now(UTC)
            self._insert_message(
                db,
                Message(
                    id=uuid4(),
                    conversation_id=turn.conversation_id,
                    turn_id=turn.id,
                    role="assistant",
                    content=question,
                    created_at=now,
                    updated_at=now,
                ),
            )
            changed = self._change_turn(
                db,
                turn,
                TurnStatus.WAITING_USER,
                input_revision=pending.revision,
                pending_input=pending,
            )
            self._insert_event(
                db, turn.conversation_id, turn.id, "input.required", pending.model_dump(mode="json")
            )
            return changed

    def accept_response(self, turn_id: UUID, request_id: UUID, revision: int, value: str) -> Turn:
        with self._transaction() as db:
            turn = self._get(db, "turns", turn_id, Turn, "TURN_NOT_FOUND")
            pending = turn.pending_input
            if (
                turn.status != TurnStatus.WAITING_USER
                or pending is None
                or pending.request_id != request_id
                or pending.revision != revision
            ):
                raise WorkbenchError("INPUT_RESPONSE_CONFLICT")
            now = datetime.now(UTC)
            if not value.strip():
                raise WorkbenchError("MESSAGE_REQUIRED")
            self._insert_message(
                db,
                Message(
                    id=uuid4(),
                    conversation_id=turn.conversation_id,
                    turn_id=turn.id,
                    role="user",
                    content=value,
                    created_at=now,
                    updated_at=now,
                ),
            )
            return self._change_turn(db, turn, TurnStatus.QUEUED, pending_input=None)

    def append_message(
        self,
        conversation_id: UUID | str,
        turn_id: UUID | str,
        role: Literal["user", "assistant"],
        content: str,
        *,
        partial: bool = False,
        dataset_ids: tuple[UUID, ...] = (),
    ) -> Message:
        now = datetime.now(UTC)
        message = Message(
            id=uuid4(),
            conversation_id=UUID(_id(conversation_id)),
            turn_id=UUID(_id(turn_id)),
            role=role,
            content=content,
            partial=partial,
            dataset_ids=dataset_ids,
            created_at=now,
            updated_at=now,
        )
        with self._transaction() as db:
            self._owned_turn(db, conversation_id, turn_id)
            self._insert_message(db, message)
        return message

    def _insert_message(self, db: sqlite3.Connection, message: Message) -> None:
        db.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
            (
                str(message.id),
                str(message.conversation_id),
                str(message.turn_id),
                message.updated_at.isoformat(),
                message.model_dump_json(),
            ),
        )
        self._insert_event(
            db,
            message.conversation_id,
            message.turn_id,
            "message.delta" if message.partial else "message.completed",
            {
                "message_id": str(message.id),
                "text": message.content,
                "role": message.role,
                "partial": message.partial,
                "dataset_ids": [str(value) for value in message.dataset_ids],
            },
        )

    def append_event(
        self,
        conversation_id: UUID | str,
        turn_id: UUID | str,
        kind: EventKind,
        payload: Mapping[str, object],
    ) -> Event:
        with self._transaction() as db:
            self._owned_turn(db, conversation_id, turn_id)
            return self._insert_event(db, conversation_id, turn_id, kind, payload)

    def _insert_event(
        self,
        db: sqlite3.Connection,
        conversation_id: UUID | str,
        turn_id: UUID | str,
        kind: EventKind,
        payload: Mapping[str, object],
    ) -> Event:
        row = db.execute(
            "UPDATE conversations SET next_seq=next_seq+1 WHERE id=? RETURNING next_seq",
            (_id(conversation_id),),
        ).fetchone()
        if row is None:
            raise ValueError("CONVERSATION_NOT_FOUND")
        now = datetime.now(UTC)
        event = Event(
            conversation_id=UUID(_id(conversation_id)),
            turn_id=UUID(_id(turn_id)),
            seq=row[0],
            kind=kind,
            payload=json.loads(_json(dict(payload))),
            created_at=now,
            updated_at=now,
        )
        db.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            (_id(conversation_id), event.seq, _id(turn_id), event.model_dump_json()),
        )
        chat = self._get(
            db, "conversations", conversation_id, Conversation, "CONVERSATION_NOT_FOUND"
        )
        project = self._get(db, "projects", chat.project_id, Project, "PROJECT_NOT_FOUND")
        for table, record in (("conversations", chat), ("projects", project)):
            data = record.model_dump()
            data["updated_at"] = now
            changed = type(record).model_validate(data)
            db.execute(
                f"UPDATE {table} SET updated_at=?, record=? WHERE id=?",
                (now.isoformat(), changed.model_dump_json(), str(record.id)),
            )
        return event

    def list_events(
        self,
        conversation_id: UUID | str,
        after: int = 0,
        limit: int = 50,
    ) -> tuple[Event, ...]:
        _limit(limit)
        if type(after) is not int or after < 0 or after > 2**63 - 1:
            raise ValueError("INVALID_CURSOR")
        with self._lock:
            self._get(
                self._db, "conversations", conversation_id, Conversation, "CONVERSATION_NOT_FOUND"
            )
            rows = self._db.execute(
                """SELECT record FROM events WHERE conversation_id=? AND seq>?
                                       ORDER BY seq LIMIT ?""",
                (_id(conversation_id), after, limit),
            ).fetchall()
        return tuple(Event.model_validate_json(row["record"]) for row in rows)

    def _page[T: Record](
        self,
        table: str,
        model: type[T],
        limit: int,
        cursor: str | None,
        scope_column: str | None = None,
        scope_id: UUID | str | None = None,
    ) -> Page[T]:
        _limit(limit)
        scope = f"{table}:{_id(scope_id) if scope_id is not None else ''}"
        clauses = []
        params: list[object] = []
        if scope_column is not None and scope_id is not None:
            clauses.append(f"{scope_column}=?")
            params.append(_id(scope_id))
        if cursor is not None:
            try:
                if len(cursor) > 1024:
                    raise ValueError
                decoded = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if not isinstance(decoded, list) or len(decoded) != 3 or decoded[0] != scope:
                    raise ValueError
                stamp = datetime.fromisoformat(decoded[1])
                if stamp.tzinfo is None:
                    raise ValueError
                identity = _id(decoded[2])
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError("INVALID_CURSOR") from exc
            clauses.append("(updated_at, id) < (?, ?)")
            params.extend((decoded[1], identity))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            rows = self._db.execute(
                f"SELECT id, updated_at, record FROM {table}{where} "
                "ORDER BY updated_at DESC, id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = base64.urlsafe_b64encode(
                _json([scope, last["updated_at"], last["id"]]).encode("utf-8")
            ).decode("ascii")
        return Page(
            items=tuple(model.model_validate_json(row["record"]) for row in rows[:limit]),
            next_cursor=next_cursor,
        )

    def list_projects(self, *, limit: int = 50, cursor: str | None = None) -> Page[Project]:
        return self._page("projects", Project, limit, cursor)

    def list_conversations(
        self,
        project_id: UUID | str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Conversation]:
        with self._lock:
            self._get(self._db, "projects", project_id, Project, "PROJECT_NOT_FOUND")
            return self._page(
                "conversations", Conversation, limit, cursor, "project_id", project_id
            )

    def list_messages(
        self,
        conversation_id: UUID | str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[Message]:
        with self._lock:
            self._get(
                self._db, "conversations", conversation_id, Conversation, "CONVERSATION_NOT_FOUND"
            )
            return self._page(
                "messages", Message, limit, cursor, "conversation_id", conversation_id
            )
