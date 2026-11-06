"""Canonical SQLite Wiki history, dependency revocation and atomic publication."""

from typing import Any
from uuid import UUID

from bioagent.knowledge.store import KnowledgeError, KnowledgeStore, _now
from bioagent.knowledge.wiki_models import WikiJob, WikiPage

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "SKIPPED"}


class WikiCatalog:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store
        with store._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS wiki_jobs (
                    id TEXT PRIMARY KEY, base_id TEXT NOT NULL, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wiki_inputs (
                    job_id TEXT PRIMARY KEY, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wiki_calls (
                    job_id TEXT NOT NULL, ordinal INTEGER NOT NULL, input_sha256 TEXT NOT NULL,
                    record TEXT NOT NULL, PRIMARY KEY(job_id,ordinal));
                CREATE TABLE IF NOT EXISTS wiki_heads (
                    id TEXT PRIMARY KEY, generation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wiki_source_epochs (
                    id TEXT PRIMARY KEY, epoch INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS wiki_pages (
                    id TEXT PRIMARY KEY, base_id TEXT NOT NULL, generation TEXT NOT NULL,
                    page_key TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0, record TEXT NOT NULL,
                    UNIQUE(generation,page_key));
                CREATE TABLE IF NOT EXISTS wiki_dependencies (
                    page_id TEXT NOT NULL, document_id TEXT, dependency_id TEXT);
                CREATE INDEX IF NOT EXISTS wiki_source ON wiki_dependencies(document_id);
                CREATE INDEX IF NOT EXISTS wiki_link ON wiki_dependencies(dependency_id);
            """)
            # Every source transition revokes in the SAME source transaction, including
            # direct store callers, failed rebuilds and all historical generations.
            cascade = """UPDATE wiki_pages SET stale=1 WHERE id IN (
                WITH RECURSIVE revoked(id) AS (
                    SELECT page_id FROM wiki_dependencies WHERE document_id=NEW.id
                    UNION SELECT d.page_id FROM wiki_dependencies d JOIN revoked r
                    ON d.dependency_id=r.id
                ) SELECT id FROM revoked);"""
            db.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS wiki_source_changed AFTER UPDATE ON documents
                WHEN NEW.deleted!=OLD.deleted OR NEW.current_revision!=OLD.current_revision
                OR NEW.published_revision IS NOT OLD.published_revision
                OR NEW.index_revision IS NOT OLD.index_revision
                OR NEW.source_sha256!=OLD.source_sha256 OR NEW.status!=OLD.status
                BEGIN {cascade}
                    INSERT INTO wiki_source_epochs VALUES(NEW.id,1)
                    ON CONFLICT(id) DO UPDATE SET epoch=epoch+1;
                END;
                CREATE TRIGGER IF NOT EXISTS wiki_base_deleted AFTER UPDATE ON bases
                WHEN NEW.deleted!=OLD.deleted BEGIN
                    UPDATE wiki_pages SET stale=1 WHERE base_id=NEW.id;
                END;
                CREATE TRIGGER IF NOT EXISTS wiki_index_requested AFTER INSERT ON index_jobs
                BEGIN {cascade.replace("NEW.id", "NEW.document_id")}
                    INSERT INTO wiki_source_epochs VALUES(NEW.document_id,1)
                    ON CONFLICT(id) DO UPDATE SET epoch=epoch+1;
                END;
            """)

    def get(self, base: str, identity: str) -> WikiJob:
        with self.store._db() as db:
            row = self.store._one(db, "wiki_jobs", identity, "WIKI_JOB_NOT_FOUND")
            if row["base_id"] != base:
                raise KnowledgeError("WIKI_JOB_NOT_FOUND")
            return WikiJob.model_validate_json(row["record"])

    def save(self, job: WikiJob, **changes: Any) -> WikiJob:
        updated = WikiJob.model_validate({**job.model_dump(), **changes, "updated_at": _now()})
        with self.store._db() as db:
            db.execute(
                "UPDATE wiki_jobs SET record=? WHERE id=?", (updated.model_dump_json(), str(job.id))
            )
        return updated

    def epochs(self, sources: tuple[Any, ...]) -> dict[str, int]:
        with self.store._db() as db:
            epochs = dict(db.execute("SELECT id,epoch FROM wiki_source_epochs"))
        return {str(s.document_id): epochs.get(str(s.document_id), 0) for s in sources}

    def insert(self, job: WikiJob) -> None:
        with self.store._db() as db:
            for row in db.execute(
                "SELECT record FROM wiki_jobs WHERE base_id=?", (str(job.base_id),)
            ):
                if WikiJob.model_validate_json(row[0]).status not in TERMINAL:
                    raise KnowledgeError("WIKI_BUILD_CONFLICT")
            db.execute(
                "INSERT INTO wiki_jobs VALUES(?,?,?)",
                (str(job.id), str(job.base_id), job.model_dump_json()),
            )

    def latest(self, base: str) -> WikiJob | None:
        self.store.base(base)
        with self.store._db() as db:
            row = db.execute(
                "SELECT record FROM wiki_jobs WHERE base_id=? ORDER BY rowid DESC LIMIT 1", (base,)
            ).fetchone()
            return WikiJob.model_validate_json(row[0]) if row else None

    def current(self, base: str) -> tuple[WikiJob | None, tuple[WikiPage, ...]]:
        self.store.base(base)
        with self.store._db() as db:
            head = db.execute("SELECT generation FROM wiki_heads WHERE id=?", (base,)).fetchone()
            if head is None:
                return None, ()
            row = db.execute(
                "SELECT record FROM wiki_jobs WHERE json_extract(record,'$.generation')=?",
                (head[0],),
            ).fetchone()
            job = WikiJob.model_validate_json(row[0])
            pages = []
            for row in db.execute(
                "SELECT record,stale FROM wiki_pages WHERE generation=? ORDER BY rowid", (head[0],)
            ):
                page = WikiPage.model_validate_json(row[0])
                if row[1]:
                    # No revoked text/citations/links escape via list or export.
                    page = page.model_copy(
                        update={"status": "STALE", "statements": (), "links": ()}
                    )
                pages.append(page)
            return job, tuple(pages)

    def invalidate(self, page_id: UUID) -> None:
        with self.store._db() as db:
            db.execute(
                """UPDATE wiki_pages SET stale=1 WHERE id IN (
                WITH RECURSIVE revoked(id) AS (SELECT ? UNION
                    SELECT d.page_id FROM wiki_dependencies d
                    JOIN revoked r ON d.dependency_id=r.id)
                SELECT id FROM revoked)""",
                (str(page_id),),
            )

    def publish(self, job: WikiJob, pages: tuple[WikiPage, ...]) -> None:
        # Caller holds the shared KnowledgeStore transaction and verifies frozen
        # sources plus complete page graph before this single pointer swap.
        with self.store._db() as db:
            if self.get(str(job.base_id), str(job.id)).status != "BUILDING":
                raise KnowledgeError("WIKI_BUILD_CONFLICT")
            keys = {p.key: str(p.id) for p in pages}
            for page in pages:
                db.execute(
                    "INSERT INTO wiki_pages VALUES(?,?,?,?,0,?)",
                    (
                        str(page.id),
                        str(job.base_id),
                        str(job.generation),
                        page.key,
                        page.model_dump_json(),
                    ),
                )
                documents = {
                    str(c.reference.document_id) for s in page.statements for c in s.citations
                }
                db.executemany(
                    "INSERT INTO wiki_dependencies VALUES(?,?,NULL)",
                    [(str(page.id), doc) for doc in documents],
                )
                db.executemany(
                    "INSERT INTO wiki_dependencies VALUES(?,NULL,?)",
                    [(str(page.id), keys[key]) for key in page.links],
                )
            db.execute(
                "INSERT INTO wiki_heads VALUES(?,?) ON CONFLICT(id) "
                "DO UPDATE SET generation=excluded.generation",
                (str(job.base_id), str(job.generation)),
            )
            self.save(job, status="COMPLETED", stage="published")

    def recover(self) -> None:
        with self.store._db() as db:
            for row in db.execute("SELECT record FROM wiki_jobs").fetchall():
                job = WikiJob.model_validate_json(row[0])
                if job.status not in TERMINAL:
                    self.save(
                        job, status="FAILED", stage="interrupted", error_code="WIKI_INTERRUPTED"
                    )
