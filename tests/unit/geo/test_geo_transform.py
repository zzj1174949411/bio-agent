from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from bioagent.geo.models import DataKind, GeoCandidate, GeoSample, GeoSource
from bioagent.geo.transform import (
    GeoTransformError,
    SourceSelection,
    selection_hash,
    transform_selection,
)


def _source_and_candidate(kind: DataKind = DataKind.RAW_COUNTS) -> tuple[GeoSource, GeoCandidate]:
    source_id = uuid4()
    candidate = GeoCandidate(
        id=uuid4(),
        source_id=source_id,
        accession="GSE12345",
        url="https://ftp.ncbi.nlm.nih.gov/geo/counts.tsv.gz",
        file_name="counts.tsv.gz",
        data_kind=kind,
        evidence=("NCBI generated raw counts",),
        compression="GZIP",
    )
    source = GeoSource(
        id=source_id,
        accession="GSE12345",
        retrieved_at="2026-09-09T00:00:00Z",
        samples=tuple(GeoSample(accession=f"GSM{i}") for i in range(1, 7)),
        candidates=(candidate,),
    )
    return source, candidate


def _selection(
    source: GeoSource,
    candidate: GeoCandidate,
    *,
    sample_columns: tuple[str, ...] = ("GSM1", "GSM2", "GSM3", "GSM4"),
) -> SourceSelection:
    groups = {
        sample: ("treated" if index < 2 else "control")
        for index, sample in enumerate(sample_columns)
    }
    return SourceSelection(
        source_id=source.id,
        candidate_id=candidate.id,
        raw_sha256="a" * 64,
        feature_column="gene_id",
        sample_columns=sample_columns,
        sample_map={column: column for column in sample_columns},
        groups=groups,
        numerator="treated",
        denominator="control",
        revision=1,
        excluded_samples=tuple(
            sample for sample in ("GSM5", "GSM6") if sample not in sample_columns
        ),
        evidence=("GSM accession matched exactly",),
    )


def _bind(selection: SourceSelection, path: Path) -> SourceSelection:
    return selection.model_copy(
        update={"raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    )


def test_selection_hash_binds_sample_assignment() -> None:
    first = {"sample_map": {"column_a": "GSM1"}, "revision": 1}
    reordered = {"revision": 1, "sample_map": {"column_a": "GSM1"}}
    changed = {"sample_map": {"column_a": "GSM2"}, "revision": 1}

    assert selection_hash("a" * 64, first) == selection_hash("a" * 64, reordered)
    assert selection_hash("a" * 64, first) != selection_hash("a" * 64, changed)


def test_transform_preserves_ids_excludes_annotation_and_writes_metadata(tmp_path: Path) -> None:
    source, candidate = _source_and_candidate()
    path = tmp_path / "counts.tsv.gz"
    raw = (
        b"gene_id\tGSM1\tGSM2\tGSM3\tGSM4\tannotation\n"
        b"00001\t1\t2\t3\t4\talpha\n"
        b"00002\t5\t6\t7\t8\tbeta\n"
    )
    path.write_bytes(gzip.compress(raw))
    before = path.read_bytes()

    result = transform_selection(
        path, source, candidate, _bind(_selection(source, candidate), path)
    )

    assert path.read_bytes() == before
    assert list(result.counts.index) == ["00001", "00002"]
    assert result.counts.columns.tolist() == ["GSM1", "GSM2", "GSM3", "GSM4"]
    assert result.counts.loc["00001", "GSM3"] == 3
    assert list(result.metadata.index) == ["GSM1", "GSM2", "GSM3", "GSM4"]
    assert result.metadata["condition"].tolist() == ["treated", "treated", "control", "control"]
    assert result.excluded_samples == ("GSM5", "GSM6")


def test_transform_rejects_normalized_candidate_and_unconfirmed_unknown(tmp_path: Path) -> None:
    path = tmp_path / "counts.csv"
    path.write_text("gene_id,GSM1,GSM2,GSM3,GSM4\nG1,1,2,3,4\n", encoding="utf-8")
    source, normalized = _source_and_candidate(DataKind.NORMALIZED)

    with pytest.raises(GeoTransformError, match="GEO_COUNTS_INVALID"):
        transform_selection(path, source, normalized, _bind(_selection(source, normalized), path))

    source, unknown = _source_and_candidate(DataKind.UNKNOWN)
    with pytest.raises(GeoTransformError, match="GEO_COUNTS_INVALID"):
        transform_selection(path, source, unknown, _bind(_selection(source, unknown), path))


def test_transform_accepts_unknown_only_after_explicit_raw_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "counts.csv"
    path.write_text(
        "gene_id,GSM1,GSM2,GSM3,GSM4\nG1,1,2,3,4\n",
        encoding="utf-8",
    )
    source, unknown = _source_and_candidate(DataKind.UNKNOWN)
    selection = _bind(
        _selection(source, unknown).model_copy(update={"confirmed_raw_type": "RAW_COUNTS"}),
        path,
    )

    result = transform_selection(path, source, unknown, selection)

    assert isinstance(result.counts, pd.DataFrame)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ("1.5,2,3,4", "NON_INTEGER_COUNT"),
        ("-1,2,3,4", "NEGATIVE_COUNT"),
    ],
)
def test_transform_rejects_non_integer_or_negative_counts(
    tmp_path: Path, values: str, message: str
) -> None:
    path = tmp_path / "counts.csv"
    path.write_text(f"gene_id,GSM1,GSM2,GSM3,GSM4\nG1,{values}\n", encoding="utf-8")
    source, candidate = _source_and_candidate()

    with pytest.raises(GeoTransformError, match=message):
        transform_selection(path, source, candidate, _bind(_selection(source, candidate), path))


def test_selection_rejects_duplicate_sample_mapping_and_feature_as_sample() -> None:
    source, candidate = _source_and_candidate()

    with pytest.raises(ValueError):
        payload = _selection(source, candidate).model_dump()
        payload["sample_map"] = {
            "gene_id": "GSM1",
            "GSM2": "GSM1",
            "GSM3": "GSM3",
            "GSM4": "GSM4",
        }
        SourceSelection.model_validate(payload)
    with pytest.raises(ValueError):
        payload = _selection(source, candidate).model_dump()
        payload["feature_column"] = "GSM1"
        SourceSelection.model_validate(payload)


def test_three_group_import_requires_explicit_subset_and_records_exclusions(tmp_path: Path) -> None:
    path = tmp_path / "counts.csv"
    path.write_text(
        "gene_id,GSM1,GSM2,GSM3,GSM4,GSM5,GSM6\nG1,1,2,3,4,5,6\n",
        encoding="utf-8",
    )
    source, candidate = _source_and_candidate()
    selection = SourceSelection(
        source_id=source.id,
        candidate_id=candidate.id,
        raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        feature_column="gene_id",
        sample_columns=("GSM1", "GSM2", "GSM3", "GSM4"),
        sample_map={"GSM1": "GSM1", "GSM2": "GSM2", "GSM3": "GSM3", "GSM4": "GSM4"},
        groups={"GSM1": "A", "GSM2": "A", "GSM3": "B", "GSM4": "B"},
        numerator="A",
        denominator="B",
        revision=2,
        excluded_samples=("GSM5", "GSM6"),
        evidence=("user selected two groups",),
    )

    result = transform_selection(path, source, candidate, selection)

    assert result.excluded_samples == ("GSM5", "GSM6")
