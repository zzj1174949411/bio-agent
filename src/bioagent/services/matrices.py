"""Persisted single-matrix confirmations; no uploaded content is executable."""

import csv
import json
import re
import sqlite3
from hashlib import sha256
from io import StringIO
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import psutil
from pydantic import BaseModel, ConfigDict, Field

from bioagent.services.datasets import DatasetImportError, DatasetImportService, ImportLimits
from bioagent.workbench.store import WorkbenchStore


class MatrixConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    direction: Literal["genes_rows", "samples_rows"]
    id_column: int = Field(ge=0)
    sample_columns: list[int] = Field(min_length=4, max_length=9999)
    groups: dict[str, str]
    numerator: str = Field(min_length=1, max_length=80)
    denominator: str = Field(min_length=1, max_length=80)
    data_type: Literal["RAW_COUNTS", "TPM", "FPKM", "LOG", "UNKNOWN"]
    source: str = Field(min_length=1, max_length=2000)
    goal: str = Field(min_length=1, max_length=4096)
    profile_id: UUID


def fail(code: str) -> None:
    raise DatasetImportError(code)


def _parse_worker(
    connection: Connection,
    raw: bytes,
    suffix: str,
    limits: ImportLimits,
    output: str,
    direction: str,
) -> None:
    try:
        DatasetImportService._check_bytes(raw, suffix, limits)
        rows = list(
            csv.reader(
                StringIO(raw.decode("utf-8-sig")),
                delimiter="," if suffix == ".csv" else "\t",
                strict=True,
            )
        )
        if len(rows) < 2 or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            fail("MATRIX_RAGGED_OR_EMPTY")
        if direction == "samples_rows":
            if len(rows) > limits.max_columns:
                fail("MATRIX_TRANSPOSE_DIMENSION_LIMIT")
            rows = [list(row) for row in zip(*rows, strict=True)]
        Path(output).write_text(json.dumps(rows), encoding="utf-8")
        connection.send(("ok", None))
    except DatasetImportError as error:
        connection.send(("error", error.code))
    except (ValueError, UnicodeError, csv.Error):
        connection.send(("error", "MATRIX_INVALID_CSV_OR_LIMIT"))
    finally:
        connection.close()


class MatrixService:
    def __init__(self, path: Path, importer: DatasetImportService | None = None):
        self.path, self.importer = path, importer
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS matrices "
                "(id TEXT PRIMARY KEY, chat TEXT NOT NULL, raw BLOB NOT NULL, record TEXT NOT NULL)"
            )

    def db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=120)

    def recover(self, workbench: WorkbenchStore) -> None:
        """Startup only, before accepting requests: interrupted plans are never replayed."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for identity, raw in db.execute("SELECT id,record FROM matrices").fetchall():
                record = json.loads(raw)
                if record["status"] != "PLANNING":
                    continue
                record.update(status="FAILED", error_code="MATRIX_PLANNING_INTERRUPTED")
                if record.get("turn_id"):
                    workbench.fail_turn(UUID(record["turn_id"]), "MATRIX_PLANNING_INTERRUPTED")
                db.execute(
                    "UPDATE matrices SET record=? WHERE id=?", (json.dumps(record), identity)
                )

    def rows(self, raw: bytes, suffix: str, direction: str = "genes_rows") -> list[list[str]]:
        limits = (
            self.importer.upload_limits
            if self.importer
            else ImportLimits(10485760, 100000, 10000, 10)
        )
        if suffix not in {".csv", ".tsv"}:
            fail("MATRIX_CSV_TSV_ONLY")
        if len(raw) > limits.max_bytes:
            fail("UPLOAD_TOO_LARGE")
        receiver, sender = get_context("spawn").Pipe(duplex=False)
        temporary = TemporaryDirectory(prefix="bioagent-matrix-")
        output = str(Path(temporary.name) / "rows.json")
        worker = get_context("spawn").Process(
            target=_parse_worker, args=(sender, raw, suffix, limits, output, direction)
        )
        worker.start()
        sender.close()
        start = monotonic()
        try:
            while not receiver.poll(0.05):
                if monotonic() - start > limits.parse_timeout_seconds:
                    fail("MATRIX_PARSE_TIMEOUT")
                if not worker.is_alive():
                    fail("MATRIX_PARSE_FAILED")
                try:
                    if psutil.Process(worker.pid).memory_info().rss > 512 * 1024 * 1024:
                        fail("MATRIX_MEMORY_LIMIT")
                except psutil.NoSuchProcess:
                    pass
            try:
                result = receiver.recv()
            except EOFError:
                fail("MATRIX_PARSE_FAILED")
            if result[0] != "ok":
                fail(result[1])
            if Path(output).stat().st_size > 100 * 1024 * 1024:
                fail("MATRIX_OUTPUT_LIMIT")
            rows = json.loads(Path(output).read_text(encoding="utf-8"))
            return cast(list[list[str]], rows)
        finally:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)
            receiver.close()
            temporary.cleanup()

    def upload(self, chat: str, raw: bytes, suffix: str) -> dict[str, Any]:
        self.rows(raw, suffix)
        identity = str(uuid4())
        record = {
            "id": identity,
            "revision": 1,
            "sha256": sha256(raw).hexdigest(),
            "suffix": suffix,
            "status": "DRAFT",
        }
        with self.db() as db:
            db.execute(
                "INSERT INTO matrices VALUES(?,?,?,?)", (identity, chat, raw, json.dumps(record))
            )
        return self.get(chat, identity)

    def read(
        self, db: sqlite3.Connection, chat: str, identity: str
    ) -> tuple[bytes, dict[str, Any]]:
        row = db.execute(
            "SELECT raw,record FROM matrices WHERE id=? AND chat=?", (identity, chat)
        ).fetchone()
        if row is None:
            fail("MATRIX_NOT_FOUND")
        raw, record = row[0], json.loads(row[1])
        if sha256(raw).hexdigest() != record["sha256"]:
            fail("MATRIX_INTEGRITY_FAILED")
        return raw, record

    def get(self, chat: str, identity: str, direction: str = "genes_rows") -> dict[str, Any]:
        with self.db() as db:
            raw, record = self.read(db, chat, identity)
        rows = self.rows(raw, record["suffix"], direction)
        return {**record, "headers": rows[0], "row_count": len(rows) - 1, "preview": rows[1:6]}

    def latest(self, chat: str) -> dict[str, Any] | None:
        with self.db() as db:
            row = db.execute(
                "SELECT id FROM matrices WHERE chat=? ORDER BY rowid DESC LIMIT 1", (chat,)
            ).fetchone()
        return self.get(chat, row[0]) if row else None

    def normalize(
        self, raw: bytes, suffix: str, request: MatrixConfirmation
    ) -> tuple[bytes, bytes]:
        if request.data_type != "RAW_COUNTS" or not request.source.strip():
            fail("MATRIX_RAW_COUNTS_CONFIRMATION_REQUIRED")
        rows = self.rows(raw, suffix, request.direction)
        headers, values = rows[0], rows[1:]
        selected = request.sample_columns
        if (
            any(i < 0 for i in selected)
            or len(set(selected)) != len(selected)
            or request.id_column in selected
            or max([request.id_column, *selected]) >= len(headers)
        ):
            fail("MATRIX_COLUMN_SELECTION_INVALID")
        samples = [headers[i] for i in selected]
        genes = [row[request.id_column] for row in values]
        for ids in (samples, genes):
            if len(set(ids)) != len(ids) or any(
                not re.fullmatch(r"[\w.:|+-]{1,256}", value) for value in ids
            ):
                fail("MATRIX_EMPTY_DUPLICATE_OR_UNSAFE_ID")
        labels = [request.groups.get(str(i), "") for i in selected]
        if (
            request.numerator == request.denominator
            or set(labels) != {request.numerator, request.denominator}
            or any(labels.count(label) < 2 for label in set(labels))
        ):
            fail("MATRIX_TWO_GROUPS_MIN_TWO_REQUIRED")
        if any(not re.fullmatch(r"[\w.-]{1,80}", label) for label in labels):
            fail("MATRIX_GROUP_LABEL_INVALID")
        counts, metadata = StringIO(), StringIO()
        writer = csv.writer(counts, lineterminator="\n")
        writer.writerow(["feature_id", *samples])
        started = monotonic()
        for gene, row in zip(genes, values, strict=True):
            if monotonic() - started > 10:
                fail("MATRIX_NORMALIZATION_TIMEOUT")
            cells = [row[i] for i in selected]
            if any(
                not re.fullmatch(r"[0-9]{1,10}", cell) or int(cell) > 2147483647 for cell in cells
            ):
                fail("MATRIX_REQUIRES_FINITE_NONNEGATIVE_INTEGER_COUNTS")
            writer.writerow([gene, *cells])
        writer = csv.writer(metadata, lineterminator="\n")
        writer.writerow(["sample_id", "condition"])
        writer.writerows(zip(samples, labels, strict=True))
        return counts.getvalue().encode(), metadata.getvalue().encode()
