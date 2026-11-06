"""Index jobs and compare-and-publish use the authoritative knowledge transaction."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from bioagent.knowledge.retrieval_models import IndexJob, IndexState
from bioagent.knowledge.store import KnowledgeError, KnowledgeStore, _now, identifier


class IndexCatalog:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store
        with store._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS index_jobs (id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS indexes (id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL, parse_revision TEXT NOT NULL,
                    model_identity TEXT NOT NULL, dimension INTEGER NOT NULL,
                    manifest_sha256 TEXT NOT NULL);
            """)

    def enqueue(self, document_id: str, model: str, dimension: int) -> IndexJob:
        doc = self.store.document(document_id)
        if doc["published_revision"] is None:
            raise KnowledgeError("REVISION_NOT_PUBLISHED")
        # Complete Task 38 integrity check before accepting a build.
        self.store.parsed(document_id, doc["published_revision"])
        with self.store._db() as db:
            current = self.store._one(db, "documents", document_id, "DOCUMENT_NOT_FOUND")
            self.store._one(db, "bases", current["base_id"], "BASE_NOT_FOUND")
            if current["published_revision"] != doc["published_revision"]:
                raise KnowledgeError("INDEX_CONFLICT")
            for row in db.execute(
                "SELECT record FROM index_jobs WHERE document_id=?", (document_id,)
            ):
                job = IndexJob.model_validate_json(row[0])
                if job.status in {"QUEUED", "INDEXING"}:
                    return job
            job = IndexJob(
                id=uuid4(),
                document_id=UUID(document_id),
                parse_revision=UUID(current["published_revision"]),
                index_revision=uuid4(),
                model_identity=model,
                dimension=dimension,
                status="QUEUED",
                created_at=_now(),
                updated_at=_now(),
            )
            db.execute(
                "INSERT INTO index_jobs VALUES(?,?,?)",
                (str(job.id), document_id, job.model_dump_json()),
            )
            return job

    def job(self, identity: str) -> IndexJob:
        with self.store._db() as db:
            row = self.store._one(db, "index_jobs", identity, "INDEX_NOT_FOUND")
            return IndexJob.model_validate_json(row["record"])

    def state(self, document_id: str) -> IndexState:
        doc = self.store.document(document_id)
        with self.store._db() as db:
            jobs = [
                IndexJob.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT record FROM index_jobs WHERE document_id=?", (document_id,)
                )
            ]
        return IndexState(
            document_id=UUID(document_id),
            index_revision=doc["index_revision"],
            latest_job=max(jobs, key=lambda job: job.created_at) if jobs else None,
        )

    def _save(self, job: IndexJob, **changes: Any) -> IndexJob:
        updated = IndexJob.model_validate({**job.model_dump(), **changes, "updated_at": _now()})
        with self.store._db() as db:
            db.execute(
                "UPDATE index_jobs SET record=? WHERE id=?",
                (updated.model_dump_json(), str(job.id)),
            )
        return updated

    def claim(self) -> IndexJob | None:
        with self.store._db() as db:
            for row in db.execute("SELECT record FROM index_jobs ORDER BY rowid"):
                job = IndexJob.model_validate_json(row[0])
                if job.status == "QUEUED":
                    job = self._save(job, status="INDEXING", progress=5)
                    db.execute(
                        "UPDATE documents SET status='INDEXING' WHERE id=? "
                        "AND deleted=0 AND index_revision IS NULL",
                        (str(job.document_id),),
                    )
                    return job
        return None

    def cancel(self, identity: str) -> IndexJob:
        with self.store._db():
            job = self.job(identity)
            if job.status in {"QUEUED", "INDEXING"}:
                job = self._save(job, status="CANCELLED")
                self._restore(str(job.document_id))
            return job

    def fail(self, identity: str, code: str) -> None:
        with self.store._db():
            job = self.job(identity)
            if job.status in {"QUEUED", "INDEXING"}:
                self._save(job, status="FAILED", error_code=code)
                self._restore(str(job.document_id))

    def _restore(self, document_id: str) -> None:
        with self.store._db() as db:
            db.execute(
                "UPDATE documents SET status=CASE WHEN index_revision IS NULL "
                "THEN 'PARSED' ELSE 'READY' END WHERE id=? AND deleted=0 "
                "AND status IN ('INDEXING','READY','PARSED')",
                (document_id,),
            )

    def publish(self, identity: str, digest: str) -> bool:
        with self.store._db() as db:
            job = self.job(identity)
            doc = db.execute(
                "SELECT d.*,b.deleted AS base_deleted FROM documents d "
                "JOIN bases b ON b.id=d.base_id WHERE d.id=?",
                (str(job.document_id),),
            ).fetchone()
            if (
                job.status != "INDEXING"
                or doc is None
                or doc["deleted"]
                or doc["base_deleted"]
                or doc["published_revision"] != str(job.parse_revision)
                or doc["current_revision"] != str(job.parse_revision)
            ):
                return False
            # Recheck original/parse/raw/settings/model/assets inside the publication lock.
            self.store.parsed(str(job.document_id), str(job.parse_revision))
            self.store._verify(self.manifest_path(str(job.index_revision)), digest)
            db.execute(
                "INSERT INTO indexes VALUES(?,?,?,?,?,?)",
                (
                    str(job.index_revision),
                    str(job.document_id),
                    str(job.parse_revision),
                    job.model_identity,
                    job.dimension,
                    digest,
                ),
            )
            db.execute(
                "UPDATE documents SET status='READY',index_revision=? WHERE id=?",
                (str(job.index_revision), str(job.document_id)),
            )
            self._save(job, status="READY", progress=100)
            return True

    def manifest_path(self, revision: str) -> Path:
        return self.store._path("indexes", identifier(revision), "index.json")

    def active(self, bases: list[str] | None = None) -> list[dict[str, Any]]:
        with self.store._db() as db:
            rows = [
                dict(row)
                for row in db.execute("""SELECT i.*,d.base_id FROM indexes i
                JOIN documents d ON d.index_revision=i.id JOIN bases b ON b.id=d.base_id
                WHERE d.deleted=0 AND b.deleted=0 AND d.status='READY'
                AND d.published_revision=i.parse_revision
                AND d.current_revision=i.parse_revision""")
            ]
        return [row for row in rows if bases is None or row["base_id"] in bases]

    def recover(self) -> None:
        with self.store._db() as db:
            identities = [row[0] for row in db.execute("SELECT id FROM index_jobs")]
        for identity in identities:
            self.fail(identity, "INDEX_INTERRUPTED")
