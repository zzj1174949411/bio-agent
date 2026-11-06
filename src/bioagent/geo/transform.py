"""Deterministic GEO matrix mapping and standardisation."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import pandas as pd

from bioagent.geo.models import DataKind, GeoCandidate, GeoSource, SourceSelection

_INTEGER = re.compile(r"^(?:0|[1-9][0-9]*)$")
_MAX_R_INTEGER = 2_147_483_647
_SUPPORTED_SUFFIXES = {".csv", ".tsv", ".txt"}
_DEFAULT_MAX_MATRIX_COLUMNS = 2_002


class GeoTransformError(ValueError):
    """Stable deterministic conversion error with a user-facing code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(f"{code}: {message or code}")


@dataclass(frozen=True)
class MatrixTable:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    delimiter: str


@dataclass(frozen=True)
class MappingPreview:
    source_id: str
    candidate_id: str
    raw_sha256: str
    headers: tuple[str, ...]
    feature_columns: tuple[str, ...]
    sample_columns: tuple[str, ...]
    suggested_sample_map: dict[str, str]
    unmapped_source_samples: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedDataset:
    counts: pd.DataFrame
    metadata: pd.DataFrame
    raw_sha256: str
    selection: SourceSelection
    excluded_samples: tuple[str, ...]


def selection_hash(raw_sha256: str, selection: Mapping[str, object]) -> str:
    """Hash the candidate bytes and a canonical JSON selection payload."""

    if not re.fullmatch(r"[0-9a-f]{64}", raw_sha256):
        raise ValueError("raw_sha256 must be a lowercase SHA-256 digest")
    payload = {"raw_sha256": raw_sha256, "selection": dict(selection)}
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_text(path: Path) -> TextIO:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        inner = Path(path.stem).suffix.lower()
        if inner not in _SUPPORTED_SUFFIXES:
            raise GeoTransformError("GEO_COUNTS_INVALID", "unsupported compressed matrix suffix")
        return gzip.open(path, mode="rt", encoding="utf-8-sig", newline="")
    if suffix not in _SUPPORTED_SUFFIXES:
        raise GeoTransformError("GEO_COUNTS_INVALID", "unsupported matrix suffix")
    return path.open(mode="r", encoding="utf-8-sig", newline="")


def read_matrix(
    path: Path,
    *,
    max_rows: int = 100_000,
    max_columns: int = _DEFAULT_MAX_MATRIX_COLUMNS,
) -> MatrixTable:
    """Read only a rectangular text matrix; no pandas inference is performed."""

    try:
        with _open_text(path) as stream:
            sample = stream.read(8192)
            stream.seek(0)
            if "\t" in sample:
                delimiter = "\t"
            elif "," in sample:
                delimiter = ","
            else:
                raise GeoTransformError("GEO_COUNTS_INVALID", "cannot determine delimiter")
            reader = csv.reader(stream, delimiter=delimiter)
            try:
                header = next(reader)
            except StopIteration as error:
                raise GeoTransformError("GEO_COUNTS_INVALID", "matrix is empty") from error
            if not header or any(not name for name in header):
                raise GeoTransformError(
                    "GEO_COUNTS_INVALID", "matrix header contains an empty name"
                )
            if len(set(header)) != len(header):
                raise GeoTransformError("DUPLICATE_MATRIX_COLUMN", "matrix columns must be unique")
            if len(header) > max_columns:
                raise GeoTransformError("GEO_DATASET_LIMIT_EXCEEDED", "too many matrix columns")
            rows: list[tuple[str, ...]] = []
            for row_number, row in enumerate(reader, start=1):
                if row_number > max_rows:
                    raise GeoTransformError("GEO_DATASET_LIMIT_EXCEEDED", "too many matrix rows")
                if len(row) != len(header):
                    raise GeoTransformError(
                        "GEO_COUNTS_INVALID", "matrix row width does not match header"
                    )
                rows.append(tuple(row))
    except UnicodeDecodeError as error:
        raise GeoTransformError("INVALID_DATASET_ENCODING") from error
    except OSError as error:
        raise GeoTransformError("GEO_COUNTS_INVALID", "matrix cannot be read") from error
    return MatrixTable(tuple(header), tuple(rows), delimiter)


def _validate_candidate(source: GeoSource, candidate: GeoCandidate) -> None:
    if candidate.source_id != source.id or candidate not in source.candidates:
        raise GeoTransformError("SOURCE_CHANGED", "candidate does not belong to source")
    if candidate.data_kind in {DataKind.NORMALIZED, DataKind.UNSUPPORTED}:
        raise GeoTransformError("GEO_COUNTS_INVALID", "candidate is not raw counts")


def preview_mapping(path: Path, source: GeoSource, candidate: GeoCandidate) -> MappingPreview:
    _validate_candidate(source, candidate)
    table = read_matrix(path)
    source_samples = tuple(sample.accession for sample in source.samples)
    suggested = {column: column for column in table.headers if column in set(source_samples)}
    mapped = set(suggested.values())
    feature_columns = tuple(column for column in table.headers if column not in mapped)
    return MappingPreview(
        source_id=str(source.id),
        candidate_id=str(candidate.id),
        raw_sha256=_raw_sha256(path),
        headers=table.headers,
        feature_columns=feature_columns,
        sample_columns=tuple(suggested),
        suggested_sample_map=suggested,
        unmapped_source_samples=tuple(sample for sample in source_samples if sample not in mapped),
    )


def transform_selection(
    path: Path,
    source: GeoSource,
    candidate: GeoCandidate,
    selection: SourceSelection,
) -> NormalizedDataset:
    """Project a confirmed matrix without changing the source bytes."""

    _validate_candidate(source, candidate)
    if len(selection.sample_columns) > 2_000:
        raise GeoTransformError("GEO_DATASET_LIMIT_EXCEEDED", "too many sample columns")
    if candidate.data_kind is DataKind.UNKNOWN and selection.confirmed_raw_type != "RAW_COUNTS":
        raise GeoTransformError(
            "GEO_COUNTS_INVALID", "UNKNOWN candidate requires raw-count confirmation"
        )
    if selection.source_id != source.id or selection.candidate_id != candidate.id:
        raise GeoTransformError("SOURCE_CHANGED", "selection does not match candidate")
    raw_sha256 = _raw_sha256(path)
    if selection.raw_sha256 != raw_sha256:
        raise GeoTransformError("SOURCE_CHANGED", "selection is bound to a different file")

    table = read_matrix(path)
    columns = set(table.headers)
    if selection.feature_column not in columns:
        raise GeoTransformError("GEO_SAMPLE_MAPPING_REQUIRED", "feature column is missing")
    missing_columns = [column for column in selection.sample_columns if column not in columns]
    if missing_columns:
        raise GeoTransformError("GEO_SAMPLE_MAPPING_REQUIRED", "selected sample column is missing")
    source_samples = {sample.accession for sample in source.samples}
    selected_samples = [selection.sample_map[column] for column in selection.sample_columns]
    if not set(selected_samples) <= source_samples:
        raise GeoTransformError("GEO_SAMPLE_MAPPING_REQUIRED", "unknown GSM in sample mapping")
    excluded = set(selection.excluded_samples)
    if not excluded <= source_samples or set(selected_samples) & excluded:
        raise GeoTransformError("GEO_SAMPLE_MAPPING_REQUIRED", "invalid excluded sample set")
    if set(selected_samples) | excluded != source_samples:
        raise GeoTransformError(
            "GEO_SAMPLE_MAPPING_REQUIRED", "sample mapping silently omits a source sample"
        )
    extra_gsm_columns = [
        column
        for column in table.headers
        if column.startswith("GSM")
        and column not in selection.sample_columns
        and column not in excluded
    ]
    if extra_gsm_columns:
        raise GeoTransformError(
            "GEO_SAMPLE_MAPPING_REQUIRED", "matrix contains an unmapped GSM column"
        )

    feature_position = table.headers.index(selection.feature_column)
    sample_positions = [table.headers.index(column) for column in selection.sample_columns]
    gene_ids: list[str] = []
    count_rows: list[list[int]] = []
    for row in table.rows:
        gene_id = row[feature_position]
        if not gene_id:
            raise GeoTransformError("MISSING_FEATURE_ID", "feature IDs must not be empty")
        if gene_id in gene_ids:
            raise GeoTransformError("DUPLICATE_FEATURE_ID", "feature IDs must be unique")
        values: list[int] = []
        for position, value in zip(sample_positions, selection.sample_columns, strict=True):
            text = row[position]
            if not _INTEGER.fullmatch(text):
                code = "NEGATIVE_COUNT" if text.startswith("-") else "NON_INTEGER_COUNT"
                raise GeoTransformError(code, f"invalid count in {value}")
            number = int(text)
            if number > _MAX_R_INTEGER:
                raise GeoTransformError("COUNT_OUT_OF_RANGE", "count exceeds R integer range")
            values.append(number)
        gene_ids.append(gene_id)
        count_rows.append(values)

    counts = pd.DataFrame(
        count_rows,
        index=pd.Index(gene_ids, name="feature_id"),
        columns=selected_samples,
    )
    metadata = pd.DataFrame(
        {selection.group_factor: [selection.groups[sample] for sample in selected_samples]},
        index=pd.Index(selected_samples, name="sample_id"),
    )
    return NormalizedDataset(
        counts=counts,
        metadata=metadata,
        raw_sha256=raw_sha256,
        selection=selection,
        excluded_samples=tuple(selection.excluded_samples),
    )


# These aliases keep the service boundary descriptive while retaining a small
# public surface for callers that refer to the operation as a matrix transform.
transform_counts = transform_selection
preview_matrix = preview_mapping


__all__ = [
    "GeoTransformError",
    "MappingPreview",
    "MatrixTable",
    "NormalizedDataset",
    "SourceSelection",
    "preview_mapping",
    "preview_matrix",
    "read_matrix",
    "selection_hash",
    "transform_counts",
    "transform_selection",
]
