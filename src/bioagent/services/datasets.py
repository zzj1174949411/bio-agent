"""Shared, bounded dataset import service for browser and GEO inputs."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from io import StringIO
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import pandas as pd

from bioagent.datasets.parser import ParsedDataset, load_dataset
from bioagent.datasets.repository import DatasetRepository
from bioagent.datasets.validator import DatasetValidation, validate_dataset
from bioagent.domain.plans import Comparison
from bioagent.domain.qc import QCStatus
from bioagent.geo.transform import NormalizedDataset

_ALLOWED_SUFFIXES = {".csv", ".tsv"}
_FACTOR_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


class DatasetImportError(ValueError):
    def __init__(
        self,
        code: str,
        message: str = "dataset import failed",
        *,
        status_code: int = 422,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ImportLimits:
    max_bytes: int
    max_rows: int
    max_columns: int
    parse_timeout_seconds: float


def _comparison_for(dataset: ParsedDataset) -> Comparison:
    for position, column in enumerate(dataset.metadata.columns):
        factor = str(column)
        if not _FACTOR_PATTERN.fullmatch(factor):
            continue
        values = dataset.metadata.iloc[:, position].dropna().astype(str).unique().tolist()
        if len(values) == 2:
            return Comparison(factor=factor, numerator=values[0], denominator=values[1])
    if len(dataset.metadata.columns) == 0:
        raise DatasetImportError("MISSING_FACTOR")
    raise DatasetImportError("BINARY_FACTOR_NOT_FOUND")


def _worker(connection: Connection, counts_path: str, metadata_path: str) -> None:
    try:
        dataset = load_dataset(Path(counts_path), Path(metadata_path))
        validation = validate_dataset(dataset, _comparison_for(dataset))
        connection.send(("ok", validation))
    except DatasetImportError as error:
        connection.send(("error", error.code, error.details))
    except (OSError, TypeError, ValueError):
        connection.send(("error", "INVALID_DATASET", {}))
    finally:
        connection.close()


class DatasetImportService:
    """Perform bounded parsing and scientific validation before persistence."""

    def __init__(
        self,
        repository: DatasetRepository,
        *,
        upload_limits: ImportLimits | None = None,
        geo_limits: ImportLimits | None = None,
        max_upload_bytes: int = 10 * 1024 * 1024,
        max_rows: int = 100_000,
        max_columns: int = 10_000,
        parse_timeout_seconds: float = 10.0,
        geo_max_bytes: int = 200 * 1024 * 1024,
        geo_max_rows: int = 100_000,
        geo_max_columns: int = 2_001,
        geo_parse_timeout_seconds: float = 30.0,
    ) -> None:
        self.repository = repository
        self.upload_limits = upload_limits or ImportLimits(
            max_bytes=max_upload_bytes,
            max_rows=max_rows,
            max_columns=max_columns,
            parse_timeout_seconds=parse_timeout_seconds,
        )
        self.geo_limits = geo_limits or ImportLimits(
            max_bytes=geo_max_bytes,
            max_rows=geo_max_rows,
            max_columns=geo_max_columns,
            parse_timeout_seconds=geo_parse_timeout_seconds,
        )

    def import_uploaded(
        self,
        counts_bytes: bytes,
        metadata_bytes: bytes,
        counts_suffix: str,
        metadata_suffix: str,
    ) -> str:
        self._check_suffixes(counts_suffix, metadata_suffix)
        self._check_bytes(counts_bytes, counts_suffix, self.upload_limits)
        self._check_bytes(metadata_bytes, metadata_suffix, self.upload_limits)
        with TemporaryDirectory(prefix="bioagent-upload-") as temporary:
            root = Path(temporary)
            counts_path = root / f"counts{counts_suffix}"
            metadata_path = root / f"metadata{metadata_suffix}"
            counts_path.write_bytes(counts_bytes)
            metadata_path.write_bytes(metadata_bytes)
            self._validate_paths(counts_path, metadata_path, self.upload_limits)
        return self.repository.create(
            counts_bytes,
            metadata_bytes,
            counts_suffix,
            metadata_suffix,
        )

    def import_normalized(self, dataset: NormalizedDataset) -> str:
        """Persist a GEO projection through the same parser and validator."""

        with TemporaryDirectory(prefix="bioagent-geo-import-") as temporary:
            root = Path(temporary)
            counts_path = root / "counts.csv"
            metadata_path = root / "metadata.csv"
            self._write_standard(dataset.counts, counts_path, index_name="feature_id")
            self._write_standard(dataset.metadata, metadata_path, index_name="sample_id")
            self._check_path_limits(counts_path, self.geo_limits)
            self._check_path_limits(metadata_path, self.geo_limits)
            self._validate_paths(counts_path, metadata_path, self.geo_limits)
            counts_bytes = counts_path.read_bytes()
            metadata_bytes = metadata_path.read_bytes()
        return self.repository.create(counts_bytes, metadata_bytes, ".csv", ".csv")

    import_geo = import_normalized
    import_upload = import_uploaded

    def discard_dataset(self, dataset_id: str) -> None:
        """Compensate a dataset when GEO provenance publication cannot commit."""
        self.repository.remove(dataset_id)

    def _validate_paths(
        self, counts_path: Path, metadata_path: Path, limits: ImportLimits
    ) -> DatasetValidation:
        context = get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_worker, args=(sender, str(counts_path), str(metadata_path))
        )
        process.start()
        sender.close()
        result: tuple[object, ...] | None = None
        try:
            if not receiver.poll(limits.parse_timeout_seconds):
                raise DatasetImportError("DATASET_PARSE_TIMEOUT", status_code=408)
            try:
                message = receiver.recv()
            except EOFError as error:
                raise DatasetImportError("INVALID_DATASET") from error
            if isinstance(message, tuple):
                result = message
        finally:
            receiver.close()
            if process.is_alive():
                process.terminate()
            process.join()
            process.close()
        if result is None or not result:
            raise DatasetImportError("INVALID_DATASET")
        if result[0] == "error":
            code = (
                result[1] if len(result) > 1 and isinstance(result[1], str) else "INVALID_DATASET"
            )
            details = result[2] if len(result) > 2 and isinstance(result[2], dict) else {}
            raise DatasetImportError(code, details=details)
        if result[0] != "ok" or len(result) != 2 or not isinstance(result[1], DatasetValidation):
            raise DatasetImportError("INVALID_DATASET")
        validation = result[1]
        if not validation.is_valid:
            failures = [issue for issue in validation.qc.issues if issue.status is QCStatus.FAIL]
            code = failures[0].code if failures else "DATASET_VALIDATION_FAILED"
            raise DatasetImportError(
                code,
                details={
                    "issues": [issue.model_dump(mode="json") for issue in validation.qc.issues]
                },
            )
        return validation

    @staticmethod
    def _check_suffixes(counts_suffix: str, metadata_suffix: str) -> None:
        if counts_suffix not in _ALLOWED_SUFFIXES or metadata_suffix not in _ALLOWED_SUFFIXES:
            raise DatasetImportError("UNSUPPORTED_FILE_TYPE")

    @staticmethod
    def _check_bytes(content: bytes, suffix: str, limits: ImportLimits) -> None:
        if len(content) > limits.max_bytes:
            raise DatasetImportError("UPLOAD_TOO_LARGE", status_code=413)
        if not content:
            raise DatasetImportError("EMPTY_UPLOAD")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise DatasetImportError("INVALID_DATASET_ENCODING") from error
        separator = "," if suffix == ".csv" else "\t"
        reader = csv.reader(StringIO(text), delimiter=separator)
        started = monotonic()
        try:
            header = next(reader)
        except StopIteration:
            raise DatasetImportError("INVALID_DATASET") from None
        if len(header) > limits.max_columns:
            raise DatasetImportError("DATASET_LIMIT_EXCEEDED", status_code=413)
        for row_count, row in enumerate(reader, start=1):
            if row_count > limits.max_rows or len(row) > limits.max_columns:
                raise DatasetImportError("DATASET_LIMIT_EXCEEDED", status_code=413)
            if monotonic() - started > limits.parse_timeout_seconds:
                raise DatasetImportError("DATASET_PARSE_TIMEOUT", status_code=408)

    @staticmethod
    def _check_path_limits(path: Path, limits: ImportLimits) -> None:
        if path.stat().st_size > limits.max_bytes:
            raise DatasetImportError("GEO_DOWNLOAD_TOO_LARGE", status_code=413)
        suffix = path.suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise DatasetImportError("GEO_COUNTS_INVALID")
        DatasetImportService._check_bytes(path.read_bytes(), suffix, limits)

    @staticmethod
    def _write_standard(frame: pd.DataFrame, path: Path, *, index_name: str) -> None:
        output = frame.copy()
        output.index.name = index_name
        output.to_csv(path, index=True, lineterminator="\n")


__all__ = ["DatasetImportError", "DatasetImportService", "ImportLimits"]
