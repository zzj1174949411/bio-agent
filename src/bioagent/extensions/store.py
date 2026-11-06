"""Versioned persistence for enabled Skill records and their immutable snapshots."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Self
from uuid import UUID, uuid4

from bioagent.extensions.models import McpServerConfig, SkillRecord, SkillSnapshot
from bioagent.extensions.policy import ExtensionError, ToolDescriptor
from bioagent.extensions.skills import SkillValidationError, validate_turn_snapshots
from bioagent.workbench.store import WorkbenchStore


class SkillStore:
    """Persist Skill configuration without modifying workbench or checkpoint tables."""

    def __init__(self, path: Path) -> None:
        with WorkbenchStore(path):
            pass
        self._lock = RLock()
        self._db = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            with self._transaction() as db:
                exists = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='skill_schema_version'"
                ).fetchone()
                if exists is None:
                    db.execute("CREATE TABLE skill_schema_version (version INTEGER NOT NULL)")
                    db.execute("INSERT INTO skill_schema_version VALUES (1)")
                    db.execute("CREATE TABLE skills (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
                    db.execute(
                        """CREATE TABLE skill_snapshots (
                            skill_id TEXT NOT NULL, sha256 TEXT NOT NULL, record TEXT NOT NULL,
                            PRIMARY KEY (skill_id, sha256))"""
                    )
                versions = db.execute("SELECT version FROM skill_schema_version").fetchall()
                if tuple(row[0] for row in versions) != (1,):
                    raise SkillValidationError("SKILL_SCHEMA_UNSUPPORTED")
                mcp_exists = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='mcp_schema_version'"
                ).fetchone()
                if mcp_exists is None:
                    db.execute("CREATE TABLE mcp_schema_version (version INTEGER NOT NULL)")
                    db.execute("INSERT INTO mcp_schema_version VALUES (1)")
                    db.execute(
                        "CREATE TABLE mcp_servers (id TEXT PRIMARY KEY, record TEXT NOT NULL)"
                    )
                mcp_versions = db.execute("SELECT version FROM mcp_schema_version").fetchall()
                if tuple(row[0] for row in mcp_versions) != (1,):
                    raise SkillValidationError("MCP_SCHEMA_UNSUPPORTED")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS mcp_tools "
                    "(qualified_name TEXT PRIMARY KEY, record TEXT NOT NULL)"
                )
                db.execute("""CREATE TABLE IF NOT EXISTS mcp_approvals (
                    approval_id TEXT PRIMARY KEY, call_id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    qualified_name TEXT NOT NULL, server_revision INTEGER NOT NULL,
                    capability_revision TEXT NOT NULL, arguments_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL, decision TEXT NOT NULL,
                    used_at TEXT, revoked_at TEXT)""")
                db.execute(
                    "CREATE INDEX IF NOT EXISTS mcp_approval_turn ON mcp_approvals(turn_id)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS extension_settings "
                    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
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
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def sync(self, records: tuple[SkillRecord, ...]) -> tuple[SkillRecord, ...]:
        """Refresh scanned metadata; changed content always revokes current enablement."""
        synced: list[SkillRecord] = []
        with self._transaction() as db:
            for incoming in records:
                row = db.execute(
                    "SELECT record FROM skills WHERE id=?", (str(incoming.id),)
                ).fetchone()
                previous = SkillRecord.model_validate_json(row[0]) if row is not None else None
                enabled = bool(previous and previous.enabled and previous.sha256 == incoming.sha256)
                record = SkillRecord.model_validate({**incoming.model_dump(), "enabled": enabled})
                db.execute(
                    """INSERT INTO skills (id, record) VALUES (?, ?)
                       ON CONFLICT(id) DO UPDATE SET record=excluded.record""",
                    (str(record.id), record.model_dump_json()),
                )
                synced.append(record)
        return tuple(synced)

    def list_skills(self) -> tuple[SkillRecord, ...]:
        with self._lock:
            rows = self._db.execute("SELECT record FROM skills").fetchall()
        return tuple(
            sorted(
                (SkillRecord.model_validate_json(row[0]) for row in rows), key=lambda x: str(x.id)
            )
        )

    def get_skill(self, identity: UUID) -> SkillRecord:
        with self._lock:
            return self._get(self._db, identity)

    def set_skill_root(self, root: str) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO extension_settings(key,value) VALUES('skill_root',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (root,),
            )
            rows = db.execute("SELECT id, record FROM skills").fetchall()
            for row in rows:
                record = SkillRecord.model_validate_json(row[1])
                if record.enabled:
                    disabled = record.model_copy(update={"enabled": False})
                    db.execute(
                        "UPDATE skills SET record=? WHERE id=?",
                        (disabled.model_dump_json(), row[0]),
                    )

    def get_skill_root(self, default: str) -> str:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM extension_settings WHERE key='skill_root'"
            ).fetchone()
        return str(row[0]) if row is not None else default

    def enable(self, identity: UUID, *, expected_hash: str, snapshot: SkillSnapshot) -> SkillRecord:
        with self._transaction() as db:
            record = self._get(db, identity)
            if (
                expected_hash != record.sha256
                or snapshot.skill_id != record.id
                or snapshot.sha256 != record.sha256
            ):
                raise SkillValidationError("SKILL_HASH_CONFLICT")
            enabled = SkillRecord.model_validate({**record.model_dump(), "enabled": True})
            db.execute(
                "UPDATE skills SET record=? WHERE id=?", (enabled.model_dump_json(), str(record.id))
            )
            db.execute(
                """INSERT OR IGNORE INTO skill_snapshots (skill_id, sha256, record)
                   VALUES (?, ?, ?)""",
                (str(record.id), snapshot.sha256, snapshot.model_dump_json()),
            )
        return enabled

    def disable(self, identity: UUID) -> SkillRecord:
        with self._transaction() as db:
            record = self._get(db, identity)
            disabled = SkillRecord.model_validate({**record.model_dump(), "enabled": False})
            db.execute(
                "UPDATE skills SET record=? WHERE id=?",
                (disabled.model_dump_json(), str(record.id)),
            )
        return disabled

    def enabled_directory(self) -> tuple[SkillRecord, ...]:
        with self._lock:
            rows = self._db.execute("SELECT record FROM skills").fetchall()
        records = [SkillRecord.model_validate_json(row[0]) for row in rows]
        enabled = (record for record in records if record.enabled)
        return tuple(sorted(enabled, key=lambda item: item.name))

    def load_enabled(self, identity: UUID) -> SkillSnapshot:
        with self._lock:
            record = self._get(self._db, identity)
            if not record.enabled:
                raise SkillValidationError("SKILL_DISABLED")
            row = self._db.execute(
                "SELECT record FROM skill_snapshots WHERE skill_id=? AND sha256=?",
                (str(record.id), record.sha256),
            ).fetchone()
        if row is None:
            raise SkillValidationError("SKILL_SNAPSHOT_MISSING")
        return SkillSnapshot.model_validate_json(row[0])

    def load_turn_snapshots(self, identities: tuple[UUID, ...]) -> tuple[SkillSnapshot, ...]:
        snapshots = tuple(self.load_enabled(identity) for identity in identities)
        return validate_turn_snapshots(snapshots)

    def load_snapshot(self, identity: UUID, sha256: str) -> SkillSnapshot:
        """Resolve a persisted historical snapshot for an already-created turn only."""
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM skill_snapshots WHERE skill_id=? AND sha256=?",
                (str(identity), sha256),
            ).fetchone()
        if row is None:
            raise SkillValidationError("SKILL_SNAPSHOT_MISSING")
        return SkillSnapshot.model_validate_json(row[0])

    def save_server(self, config: McpServerConfig) -> McpServerConfig:
        """Persist configuration only; credentials remain in the caller's secret store."""
        with self._transaction() as db:
            db.execute(
                """INSERT INTO mcp_servers (id, record) VALUES (?, ?)
                   ON CONFLICT(id) DO UPDATE SET record=excluded.record""",
                (str(config.id), config.model_dump_json()),
            )
        return config

    def update_server(self, config: McpServerConfig, *, expected_revision: int) -> McpServerConfig:
        with self._transaction() as db:
            row = db.execute(
                "SELECT record FROM mcp_servers WHERE id=?", (str(config.id),)
            ).fetchone()
            if row is None:
                raise ExtensionError("MCP_SERVER_NOT_FOUND")
            current = McpServerConfig.model_validate_json(row[0])
            if current.revision != expected_revision or config.revision != expected_revision + 1:
                raise ExtensionError("MCP_SERVER_REVISION_CONFLICT")
            db.execute(
                "UPDATE mcp_servers SET record=? WHERE id=?",
                (config.model_dump_json(), str(config.id)),
            )
        return config

    def disable_server(self, identity: UUID) -> McpServerConfig:
        current = self.get_server(identity)
        updated = current.model_copy(update={"enabled": False, "revision": current.revision + 1})
        return self.update_server(updated, expected_revision=current.revision)

    def get_server(self, identity: UUID) -> McpServerConfig:
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM mcp_servers WHERE id=?", (str(identity),)
            ).fetchone()
        if row is None:
            raise SkillValidationError("MCP_SERVER_NOT_FOUND")
        return McpServerConfig.model_validate_json(row[0])

    def list_servers(self) -> tuple[McpServerConfig, ...]:
        with self._lock:
            rows = self._db.execute("SELECT record FROM mcp_servers").fetchall()
        servers = [McpServerConfig.model_validate_json(row[0]) for row in rows]
        return tuple(sorted(servers, key=lambda item: str(item.id)))

    def save_tool(self, descriptor: ToolDescriptor) -> ToolDescriptor:
        with self._transaction() as db:
            existing = db.execute(
                "SELECT record FROM mcp_tools WHERE qualified_name=?", (descriptor.qualified_name,)
            ).fetchone()
            if existing is not None:
                old = ToolDescriptor.model_validate_json(existing[0])
                if old.server_id != descriptor.server_id:
                    raise ExtensionError("TOOL_NAME_COLLISION")
            db.execute(
                "INSERT INTO mcp_tools(qualified_name,record) VALUES(?,?) "
                "ON CONFLICT(qualified_name) DO UPDATE SET record=excluded.record",
                (descriptor.qualified_name, descriptor.model_dump_json()),
            )
        return descriptor

    def get_tool(self, name: str) -> ToolDescriptor:
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM mcp_tools WHERE qualified_name=?", (name,)
            ).fetchone()
        if row is None:
            raise ExtensionError("TOOL_NOT_FOUND")
        return ToolDescriptor.model_validate_json(row[0])

    def list_tools(self) -> tuple[ToolDescriptor, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT record FROM mcp_tools ORDER BY qualified_name"
            ).fetchall()
        return tuple(ToolDescriptor.model_validate_json(row[0]) for row in rows)

    def update_tool(self, descriptor: ToolDescriptor) -> ToolDescriptor:
        return self.save_tool(descriptor)

    def create_approval(
        self,
        *,
        call_id: str,
        conversation_id: str,
        turn_id: str,
        qualified_name: str,
        server_revision: int,
        capability_revision: str,
        arguments_hash: str,
        expires_at: datetime,
    ) -> dict[str, object]:
        approval_id = str(uuid4())
        with self._transaction() as db:
            db.execute(
                """INSERT INTO mcp_approvals(
                    approval_id,call_id,conversation_id,turn_id,qualified_name,
                    server_revision,capability_revision,arguments_hash,expires_at,decision
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    approval_id,
                    call_id,
                    conversation_id,
                    turn_id,
                    qualified_name,
                    server_revision,
                    capability_revision,
                    arguments_hash,
                    expires_at.isoformat(),
                    "PENDING",
                ),
            )
        return self.get_approval(call_id)

    def get_approval(self, call_id: str) -> dict[str, object]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM mcp_approvals WHERE call_id=?", (call_id,)
            ).fetchone()
        if row is None:
            raise ExtensionError("APPROVAL_NOT_FOUND")
        return dict(row)

    def decide_approval(
        self,
        *,
        call_id: str,
        approval_id: str,
        decision: str,
        capability_revision: str,
        arguments_hash: str,
    ) -> dict[str, object]:
        with self._transaction() as db:
            row = db.execute("SELECT * FROM mcp_approvals WHERE call_id=?", (call_id,)).fetchone()
            if row is None or row["approval_id"] != approval_id:
                raise ExtensionError("APPROVAL_NOT_FOUND")
            if (
                row["capability_revision"] != capability_revision
                or row["arguments_hash"] != arguments_hash
            ):
                raise ExtensionError("APPROVAL_CONFLICT")
            if row["revoked_at"] is not None:
                raise ExtensionError("APPROVAL_REVOKED")
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
                raise ExtensionError("APPROVAL_EXPIRED")
            if row["decision"] != "PENDING":
                if row["decision"] == ("APPROVED" if decision == "approve" else "DENIED"):
                    return dict(row)
                raise ExtensionError("APPROVAL_CONFLICT")
            db.execute(
                "UPDATE mcp_approvals SET decision=? WHERE call_id=?",
                ("APPROVED" if decision == "approve" else "DENIED", call_id),
            )
        return self.get_approval(call_id)

    def consume_approval(
        self,
        *,
        call_id: str,
        approval_id: str,
        qualified_name: str,
        capability_revision: str,
        arguments_hash: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        with self._transaction() as db:
            result = db.execute(
                """UPDATE mcp_approvals SET used_at=?
                WHERE call_id=? AND approval_id=? AND qualified_name=?
                AND capability_revision=? AND arguments_hash=?
                AND decision='APPROVED' AND used_at IS NULL
                AND revoked_at IS NULL AND expires_at>?""",
                (
                    now,
                    call_id,
                    approval_id,
                    qualified_name,
                    capability_revision,
                    arguments_hash,
                    now,
                ),
            )
            if result.rowcount != 1:
                row = db.execute(
                    "SELECT * FROM mcp_approvals WHERE call_id=?", (call_id,)
                ).fetchone()
                if row is None:
                    raise ExtensionError("APPROVAL_NOT_FOUND")
                if row["revoked_at"] is not None:
                    raise ExtensionError("APPROVAL_REVOKED")
                if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
                    raise ExtensionError("APPROVAL_EXPIRED")
                if row["used_at"] is not None:
                    raise ExtensionError("APPROVAL_ALREADY_USED")
                raise ExtensionError("APPROVAL_CONFLICT")
        return self.get_approval(call_id)

    def revoke_turn(self, turn_id: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._transaction() as db:
            result = db.execute(
                "UPDATE mcp_approvals SET revoked_at=? WHERE turn_id=? "
                "AND used_at IS NULL AND revoked_at IS NULL",
                (now, turn_id),
            )
            return int(result.rowcount)

    def revoke_pending_approvals(self) -> int:
        """Invalidate unused approvals when the process is restarted."""

        now = datetime.now(UTC).isoformat()
        with self._transaction() as db:
            result = db.execute(
                "UPDATE mcp_approvals SET revoked_at=? "
                "WHERE used_at IS NULL AND revoked_at IS NULL",
                (now,),
            )
            return int(result.rowcount)

    @staticmethod
    def _get(db: sqlite3.Connection, identity: UUID) -> SkillRecord:
        row = db.execute("SELECT record FROM skills WHERE id=?", (str(identity),)).fetchone()
        if row is None:
            raise SkillValidationError("SKILL_NOT_FOUND")
        return SkillRecord.model_validate_json(row[0])
