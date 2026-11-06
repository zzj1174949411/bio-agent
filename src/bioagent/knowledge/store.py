"""Durable ingestion state and compare-and-publish boundary for local revisions."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock, local
from typing import Any
from uuid import UUID, uuid4

from bioagent.knowledge.models import ParsedDocument

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 100 * 1024 * 1024


class KnowledgeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identifier(value: str) -> str:
    try:
        parsed = UUID(value)
        if str(parsed) != value or parsed.version != 4:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise KnowledgeError("INVALID_ID") from error
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat()


class KnowledgeStore:
    def __init__(self, root: Path) -> None:
        if root.is_symlink():
            raise KnowledgeError("KNOWLEDGE_ROOT_INVALID")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._transaction_local = local()
        with self._db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS bases (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, base_id TEXT NOT NULL, filename TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL, current_revision TEXT NOT NULL,
                    published_revision TEXT, index_revision TEXT,
                    deleted INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS active_source
                    ON documents(base_id, source_sha256) WHERE deleted=0;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL UNIQUE,
                    revision INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    parsed_sha256 TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, parser_version TEXT NOT NULL,
                    settings_sha256 TEXT NOT NULL, models_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL);
            """)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            existing = getattr(self._transaction_local, "db", None)
            if existing is not None:
                yield existing
                return
            self._path("catalog.sqlite")
            db = sqlite3.connect(self.root / "catalog.sqlite", timeout=10)
            db.row_factory = sqlite3.Row
            try:
                db.execute("BEGIN IMMEDIATE")
                self._transaction_local.db = db
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                self._transaction_local.db = None
                db.close()

    def _path(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        if self.root.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise KnowledgeError("RESOURCE_INTEGRITY_FAILED")
        if any(item.is_symlink() for item in (path, *path.parents) if item != self.root.parent):
            raise KnowledgeError("RESOURCE_INTEGRITY_FAILED")
        return path

    @staticmethod
    def _one(db: sqlite3.Connection, table: str, key: str, code: str) -> dict[str, Any]:
        # table is exclusively a trusted literal at each call site.
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier(key),)).fetchone()
        if row is None:
            raise KnowledgeError(code)
        result = dict(row)
        if result.get("deleted"):
            raise KnowledgeError(code)
        result.pop("deleted", None)
        return result

    def create_base(self, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 200:
            raise KnowledgeError("BASE_NAME_INVALID")
        key = str(uuid4())
        with self._db() as db:
            db.execute("INSERT INTO bases(id,name,created_at) VALUES(?,?,?)", (key, name, _now()))
        return self.base(key)

    def bases(self) -> list[dict[str, Any]]:
        with self._db() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,name,created_at FROM bases WHERE deleted=0 ORDER BY created_at DESC"
                )
            ]

    def base(self, key: str) -> dict[str, Any]:
        with self._db() as db:
            return self._one(db, "bases", key, "BASE_NOT_FOUND")

    def rename_base(self, key: str, name: str) -> dict[str, Any]:
        if not name.strip() or len(name) > 200:
            raise KnowledgeError("BASE_NAME_INVALID")
        with self._db() as db:
            self._one(db, "bases", key, "BASE_NOT_FOUND")
            db.execute("UPDATE bases SET name=? WHERE id=?", (name.strip(), key))
        return self.base(key)

    def document(self, key: str) -> dict[str, Any]:
        with self._db() as db:
            document = self._one(db, "documents", key, "DOCUMENT_NOT_FOUND")
            self._one(db, "bases", document["base_id"], "BASE_NOT_FOUND")
            document["job"] = dict(
                db.execute(
                    "SELECT * FROM jobs WHERE revision_id=?", (document["current_revision"],)
                ).fetchone()
            )
            document["warnings"] = []
            if document["published_revision"]:
                revision = self._one(
                    db, "revisions", document["published_revision"], "REVISION_NOT_PUBLISHED"
                )
                parsed_path = self._path("documents", key, revision["id"], "parsed.json")
                self._verify(parsed_path, revision["parsed_sha256"])
                document["warnings"] = json.loads(parsed_path.read_bytes())["warnings"]
            return document

    def documents(self, base_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            self._one(db, "bases", base_id, "BASE_NOT_FOUND")
            keys = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM documents WHERE base_id=? AND deleted=0 "
                    "ORDER BY created_at DESC",
                    (base_id,),
                )
            ]
        return [self.document(key) for key in keys]

    def import_pdf(self, base_id: str, filename: str, content: bytes) -> dict[str, Any]:
        if not filename.lower().endswith(".pdf") or not content.startswith(b"%PDF-"):
            raise KnowledgeError("PDF_INVALID")
        if len(content) > MAX_PDF_BYTES:
            raise KnowledgeError("PDF_TOO_LARGE")
        # User filename is display data only; no path is derived from it.
        filename = filename.replace("\\", "/").split("/")[-1][:200]
        digest, key, revision_id = sha256(content).hexdigest(), str(uuid4()), str(uuid4())
        with self._db() as db:
            self._one(db, "bases", base_id, "BASE_NOT_FOUND")
            old = db.execute(
                "SELECT id FROM documents WHERE base_id=? AND source_sha256=? AND deleted=0",
                (base_id, digest),
            ).fetchone()
            if old is not None:
                key, duplicate = old[0], True
            else:
                folder = self._path("documents", key)
                folder.mkdir(parents=True)
                self._path("documents", key, "original.pdf").write_bytes(content)
                db.execute(
                    """INSERT INTO documents
                    (id,base_id,filename,source_sha256,created_at,status,current_revision)
                    VALUES(?,?,?,?,?,'QUEUED',?)""",
                    (key, base_id, filename, digest, _now(), revision_id),
                )
                self._new_job(db, key, revision_id, digest, 1)
                duplicate = False
        return {"document": self.document(key), "duplicate": duplicate}

    @staticmethod
    def _new_job(db: sqlite3.Connection, doc: str, rev: str, digest: str, seq: int) -> str:
        job_id, now = str(uuid4()), _now()
        db.execute(
            """INSERT INTO jobs
            (id,document_id,revision_id,revision,source_sha256,status,stage,created_at,updated_at)
            VALUES(?,?,?,?,?,'QUEUED','queued',?,?)""",
            (job_id, doc, rev, seq, digest, now, now),
        )
        return job_id

    def job(self, job_id: str) -> dict[str, Any]:
        with self._db() as db:
            job = self._one(db, "jobs", job_id, "JOB_NOT_FOUND")
            self._one(db, "documents", job["document_id"], "DOCUMENT_NOT_FOUND")
            return job

    def job_dir(self, job_id: str) -> Path:
        with self._db() as db:
            job = self._one(db, "jobs", job_id, "JOB_NOT_FOUND")
        return self._path("documents", job["document_id"], job["revision_id"])

    def claim(self) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("""SELECT j.* FROM jobs j
                JOIN documents d ON j.document_id=d.id JOIN bases b ON b.id=d.base_id
                WHERE j.status='QUEUED' AND d.deleted=0 AND b.deleted=0
                AND d.current_revision=j.revision_id ORDER BY j.created_at LIMIT 1""").fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET status='PARSING',stage='preflight',updated_at=? WHERE id=?",
                (_now(), row["id"]),
            )
            db.execute("UPDATE documents SET status='PARSING' WHERE id=?", (row["document_id"],))
            return {**dict(row), "status": "PARSING", "stage": "preflight"}

    def progress(self, job_id: str, stage: str, value: int) -> None:
        with self._db() as db:
            db.execute(
                """UPDATE jobs SET stage=?,progress=?,updated_at=?
                WHERE id=? AND status='PARSING'""",
                (stage, value, _now(), identifier(job_id)),
            )

    def fail(self, job_id: str, code: str) -> None:
        with self._db() as db:
            job = self._one(db, "jobs", job_id, "JOB_NOT_FOUND")
            if job["status"] not in {"PARSING", "QUEUED"}:
                return
            db.execute(
                "UPDATE jobs SET status='FAILED',stage='failed',error_code=?,updated_at=? "
                "WHERE id=?",
                (code, _now(), job_id),
            )
            db.execute(
                "UPDATE documents SET status='FAILED' WHERE id=? AND current_revision=? "
                "AND deleted=0",
                (job["document_id"], job["revision_id"]),
            )

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._db() as db:
            job = self._one(db, "jobs", job_id, "JOB_NOT_FOUND")
            self._one(db, "documents", job["document_id"], "DOCUMENT_NOT_FOUND")
            if job["status"] == "PARSED":
                raise KnowledgeError("JOB_CONFLICT")
            if job["status"] in {"QUEUED", "PARSING"}:
                db.execute(
                    "UPDATE jobs SET status='CANCELLED',stage='cancelled',updated_at=? WHERE id=?",
                    (_now(), job_id),
                )
                db.execute(
                    "UPDATE documents SET status='CANCELLED' WHERE id=? AND current_revision=?",
                    (job["document_id"], job["revision_id"]),
                )
        return self.job(job_id)

    def retry(self, document_id: str) -> dict[str, Any]:
        with self._db() as db:
            doc = self._one(db, "documents", document_id, "DOCUMENT_NOT_FOUND")
            self._one(db, "bases", doc["base_id"], "BASE_NOT_FOUND")
            if doc["status"] not in {"FAILED", "CANCELLED"}:
                raise KnowledgeError("JOB_CONFLICT")
            seq = (
                db.execute(
                    "SELECT MAX(revision) FROM jobs WHERE document_id=?", (document_id,)
                ).fetchone()[0]
                + 1
            )
            revision_id = str(uuid4())
            job_id = self._new_job(db, document_id, revision_id, doc["source_sha256"], seq)
            db.execute(
                "UPDATE documents SET status='QUEUED',current_revision=? WHERE id=?",
                (revision_id, document_id),
            )
        return self.job(job_id)

    def recover(self) -> None:
        with self._db() as db:
            db.execute("""UPDATE documents SET status='FAILED' WHERE deleted=0
                AND current_revision IN (SELECT revision_id FROM jobs
                WHERE status IN ('QUEUED','PARSING'))""")
            db.execute(
                """UPDATE jobs SET status='FAILED',stage='failed',
                error_code='INGESTION_INTERRUPTED',updated_at=?
                WHERE status IN ('QUEUED','PARSING')""",
                (_now(),),
            )
            unpublished = [
                row[0]
                for row in db.execute("SELECT id FROM jobs WHERE status IN ('FAILED','CANCELLED')")
            ]

        for job_id in unpublished:
            # Retry cleanup on every startup if Windows still held a worker file.
            with suppress(OSError):
                self.discard(job_id)
        self.cleanup_deleted()

    def cleanup_deleted(self) -> None:
        with self._db() as db:
            keys = [row[0] for row in db.execute("SELECT id FROM documents WHERE deleted=1")]
        for key in keys:
            self.cleanup_document(key)

    def original(self, document_id: str) -> Path:
        doc = self.document(document_id)
        path = self._path("documents", doc["id"], "original.pdf")
        self._verify(path, doc["source_sha256"])
        return path

    @staticmethod
    def _verify(path: Path, digest: str) -> None:
        try:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > MAX_OUTPUT_BYTES
                or file_hash(path) != digest
            ):
                raise KnowledgeError("RESOURCE_INTEGRITY_FAILED")
        except OSError as error:
            raise KnowledgeError("RESOURCE_INTEGRITY_FAILED") from error

    def publish(self, job_id: str) -> bool:
        # Keep DB lock through verification and publication: cancel/delete are linearized.
        with self._db() as db:
            job = self._one(db, "jobs", job_id, "JOB_NOT_FOUND")
            row = db.execute("SELECT * FROM documents WHERE id=?", (job["document_id"],)).fetchone()
            if (
                row is None
                or row["deleted"]
                or job["status"] != "PARSING"
                or (row["current_revision"] != job["revision_id"])
            ):
                return False
            self._one(db, "bases", row["base_id"], "BASE_NOT_FOUND")
            folder = self._path("documents", job["document_id"], job["revision_id"])
            parsed_path = self._path(
                "documents", job["document_id"], job["revision_id"], "parsed.json"
            )
            if not parsed_path.is_file() or parsed_path.stat().st_size > MAX_OUTPUT_BYTES:
                raise KnowledgeError("PARSE_OUTPUT_INVALID")
            payload = parsed_path.read_bytes()
            try:
                parsed = ParsedDocument.model_validate_json(payload)
            except ValueError as error:
                raise KnowledgeError("PARSE_OUTPUT_INVALID") from error
            if parsed.source_sha256 != row["source_sha256"]:
                raise KnowledgeError("RESOURCE_INTEGRITY_FAILED")
            self._verify(self._path("documents", row["id"], "original.pdf"), row["source_sha256"])
            self._verify(folder / "docling.json", parsed.raw_sha256)
            self._verify(folder / "settings.json", parsed.settings_sha256)
            self._verify(folder / "models.json", parsed.models_sha256)
            total = sum(path.stat().st_size for path in folder.iterdir() if path.is_file())
            for asset in parsed.assets:
                path = self._path("documents", row["id"], job["revision_id"], f"{asset.id}.png")
                self._verify(path, asset.sha256)
            if total > MAX_OUTPUT_BYTES:
                raise KnowledgeError("PARSE_OUTPUT_TOO_LARGE")
            db.execute(
                "INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    job["revision_id"],
                    row["id"],
                    job_id,
                    sha256(payload).hexdigest(),
                    parsed.raw_sha256,
                    parsed.source_sha256,
                    parsed.parser_version,
                    parsed.settings_sha256,
                    parsed.models_sha256,
                    _now(),
                ),
            )
            db.execute(
                "UPDATE jobs SET status='PARSED',stage='parsed',progress=100,updated_at=? "
                "WHERE id=?",
                (_now(), job_id),
            )
            db.execute(
                "UPDATE documents SET status='PARSED',published_revision=?,"
                "index_revision=NULL WHERE id=?",
                (job["revision_id"], row["id"]),
            )
            return True

    def parsed(self, document_id: str, revision_id: str) -> dict[str, Any]:
        identifier(revision_id)
        with self._db() as db:
            doc = self._one(db, "documents", document_id, "DOCUMENT_NOT_FOUND")
            self._one(db, "bases", doc["base_id"], "BASE_NOT_FOUND")
            if doc["published_revision"] != revision_id or doc["status"] not in {
                "PARSED",
                "INDEXING",
                "READY",
            }:
                raise KnowledgeError("REVISION_NOT_PUBLISHED")
            revision = self._one(db, "revisions", revision_id, "REVISION_NOT_PUBLISHED")
            folder = self._path("documents", document_id, revision_id)
            self._verify(folder / "parsed.json", revision["parsed_sha256"])
            self._verify(folder / "docling.json", revision["raw_sha256"])
            self._verify(folder / "settings.json", revision["settings_sha256"])
            self._verify(folder / "models.json", revision["models_sha256"])
            self._verify(self._path("documents", document_id, "original.pdf"), doc["source_sha256"])
            payload = json.loads((folder / "parsed.json").read_bytes())
            for asset in payload["assets"]:
                self._verify(
                    self._path(
                        "documents", document_id, revision_id, f"{identifier(asset['id'])}.png"
                    ),
                    asset["sha256"],
                )
            return {
                "document_id": document_id,
                "base_id": doc["base_id"],
                "revision_id": revision_id,
                "parsed_sha256": revision["parsed_sha256"],
                **payload,
            }

    def asset(self, document_id: str, revision_id: str, asset_id: str) -> Path:
        identifier(asset_id)
        parsed = self.parsed(document_id, revision_id)
        if not any(asset["id"] == asset_id for asset in parsed["assets"]):
            raise KnowledgeError("ASSET_NOT_FOUND")
        return self._path("documents", document_id, revision_id, f"{asset_id}.png")

    def delete_document(self, document_id: str) -> None:
        with self._db() as db:
            self._one(db, "documents", document_id, "DOCUMENT_NOT_FOUND")
            self._tombstone(db, document_id)
        self.cleanup_document(document_id)

    @staticmethod
    def _tombstone(db: sqlite3.Connection, document_id: str) -> None:
        db.execute(
            "UPDATE documents SET deleted=1,status='DELETED',published_revision=NULL,"
            "index_revision=NULL WHERE id=?",
            (document_id,),
        )
        db.execute(
            "UPDATE jobs SET status='CANCELLED',stage='deleted',updated_at=? "
            "WHERE document_id=? AND status IN ('QUEUED','PARSING')",
            (_now(), document_id),
        )

    def cleanup_document(self, document_id: str) -> None:
        folder = self._path("documents", identifier(document_id))
        if folder.is_dir():
            # Windows may still hold an active worker's files. The supervisor also
            # discards the unpublished revision after killing that worker.
            with suppress(OSError):
                shutil.rmtree(folder)

    def discard(self, job_id: str) -> None:
        with self._db() as db:
            job = self._one(db, "jobs", job_id, "JOB_NOT_FOUND")
            deleted = db.execute(
                "SELECT deleted FROM documents WHERE id=?", (job["document_id"],)
            ).fetchone()[0]
            if job["status"] == "PARSED" and not deleted:
                return
        if deleted:
            self.cleanup_document(job["document_id"])
            return
        folder = self.job_dir(job_id)
        if folder.is_dir():
            shutil.rmtree(folder)

    def delete_base(self, base_id: str) -> None:
        with self._db() as db:
            self._one(db, "bases", base_id, "BASE_NOT_FOUND")
            keys = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM documents WHERE base_id=? AND deleted=0", (base_id,)
                )
            ]
            db.execute("UPDATE bases SET deleted=1 WHERE id=?", (base_id,))
            for key in keys:
                self._tombstone(db, key)
        for key in keys:
            self.cleanup_document(key)
