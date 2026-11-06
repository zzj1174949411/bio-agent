from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from bioagent.datasets.repository import DatasetRepository
from bioagent.geo.models import GeoCandidate, GeoSample, GeoSearchProvenance, GeoSource
from bioagent.geo.repository import GeoRepository, GeoRepositoryError
from bioagent.geo.search_repository import GeoSearchRecord, GeoSearchRepository, GeoSearchStatus
from bioagent.geo.transform import NormalizedDataset, SourceSelection, selection_hash
from bioagent.retrieval.contracts import DatasetSearchHit, DatasetSearchQuery, EvidenceRef
from bioagent.services.datasets import DatasetImportService


def _fixture(tmp_path: Path) -> tuple[GeoSource, GeoCandidate, SourceSelection, Path]:
    source_id = uuid4()
    candidate = GeoCandidate(
        id=uuid4(),
        source_id=source_id,
        accession="GSE12345",
        url="https://ftp.ncbi.nlm.nih.gov/geo/counts.tsv",
        file_name="counts.tsv",
        data_kind="RAW_COUNTS",
        evidence=("raw counts",),
        compression="NONE",
    )
    source = GeoSource(
        id=source_id,
        accession="GSE12345",
        retrieved_at="2026-09-09T00:00:00Z",
        samples=tuple(GeoSample(accession=f"GSM{i}") for i in range(1, 5)),
        candidates=(candidate,),
    )
    raw_path = tmp_path / "download.tsv"
    raw_path.write_bytes(b"gene_id\tGSM1\tGSM2\tGSM3\tGSM4\nG1\t1\t2\t3\t4\n")
    selection = SourceSelection(
        source_id=source.id,
        candidate_id=candidate.id,
        raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        feature_column="gene_id",
        sample_columns=("GSM1", "GSM2", "GSM3", "GSM4"),
        sample_map={f"GSM{i}": f"GSM{i}" for i in range(1, 5)},
        groups={"GSM1": "A", "GSM2": "A", "GSM3": "B", "GSM4": "B"},
        numerator="A",
        denominator="B",
        revision=1,
        evidence=("exact accession mapping",),
    )
    return source, candidate, selection, raw_path


def test_repository_publishes_atomic_provenance_and_verifies_hashes(tmp_path: Path) -> None:
    source, candidate, selection, raw_path = _fixture(tmp_path)
    repository = GeoRepository(tmp_path / "sources")
    counts = pd.DataFrame({"GSM1": [1], "GSM2": [2], "GSM3": [3], "GSM4": [4]}, index=["G1"])
    metadata = pd.DataFrame(
        {"condition": ["A", "A", "B", "B"]}, index=["GSM1", "GSM2", "GSM3", "GSM4"]
    )
    before = raw_path.read_bytes()

    record = repository.publish(source, candidate, selection, raw_path, counts, metadata)

    assert raw_path.read_bytes() == before
    assert record.source_json.is_file()
    payload = json.loads(record.source_json.read_text(encoding="utf-8"))
    assert payload["accession"] == "GSE12345"
    assert payload["raw_sha256"] == record.raw_sha256
    assert payload["conversion_version"]
    assert record.counts_sha256 != record.raw_sha256
    assert repository.read(record.source_id).raw_sha256 == record.raw_sha256


def test_repository_persists_and_revalidates_selected_search_provenance(tmp_path: Path) -> None:
    source, candidate, selection, raw_path = _fixture(tmp_path)
    query = DatasetSearchQuery(text="brain")
    provenance = GeoSearchProvenance(
        search_id=uuid4(),
        query_hash=query.query_hash,
        provider="geo",
        selected_accession=source.accession,
        selection_revision=3,
        retrieved_at="2026-09-14T00:00:00Z",
        evidence_sha256="b" * 64,
    )
    search_repository = GeoSearchRepository(tmp_path / "data" / "searches")
    search_repository.write(
        GeoSearchRecord(
            id=provenance.search_id,
            status=GeoSearchStatus.SELECTED,
            revision=provenance.selection_revision + 1,
            query=query,
            query_hash=query.query_hash,
            items=(
                DatasetSearchHit(
                    provider="geo",
                    source_id=source.accession,
                    title="fixture",
                    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                    evidence=EvidenceRef(
                        provider="geo",
                        source_id=source.accession,
                        source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                        retrieved_at=provenance.retrieved_at,
                        content_sha256=provenance.evidence_sha256,
                    ),
                ),
            ),
            total=1,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            source_id=str(source.id),
            selected_accession=source.accession,
            selection_revision=provenance.selection_revision,
        )
    )
    repository = GeoRepository(tmp_path / "sources", search_repository=search_repository)
    counts = pd.DataFrame({"GSM1": [1], "GSM2": [2], "GSM3": [3], "GSM4": [4]}, index=["G1"])
    metadata = pd.DataFrame(
        {"condition": ["A", "A", "B", "B"]}, index=["GSM1", "GSM2", "GSM3", "GSM4"]
    )

    record = repository.publish(
        source, candidate, selection, raw_path, counts, metadata, provenance=provenance
    )

    payload = json.loads(record.source_json.read_text(encoding="utf-8"))
    assert payload["search_provenance"]["selected_accession"] == "GSE12345"
    assert repository.read(record.source_id).search_provenance == provenance

    with pytest.raises(GeoRepositoryError, match="GEO_SEARCH_PROVENANCE_INVALID"):
        repository.publish(
            source,
            candidate,
            selection,
            raw_path,
            counts,
            metadata,
            provenance=provenance.model_copy(update={"evidence_sha256": "c" * 64}),
        )

    payload.pop("search_provenance")
    payload.pop("search_provenance_sha256")
    record.source_json.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GeoRepositoryError, match="GEO_SEARCH_PROVENANCE_INVALID"):
        repository.read(record.source_id)

    replacement = provenance.model_copy(update={"search_id": uuid4()})
    search_repository.write(
        GeoSearchRecord(
            id=replacement.search_id,
            status=GeoSearchStatus.SELECTED,
            revision=replacement.selection_revision + 1,
            query=query,
            query_hash=query.query_hash,
            items=(
                DatasetSearchHit(
                    provider="geo",
                    source_id=source.accession,
                    title="same accession, other selected source",
                    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                    evidence=EvidenceRef(
                        provider="geo",
                        source_id=source.accession,
                        source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                        retrieved_at=replacement.retrieved_at,
                        content_sha256=replacement.evidence_sha256,
                    ),
                ),
            ),
            total=1,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            source_id=str(uuid4()),
            selected_accession=source.accession,
            selection_revision=replacement.selection_revision,
        )
    )
    payload["search_provenance"] = replacement.model_dump(mode="json")
    payload["search_provenance_sha256"] = replacement.provenance_sha256
    record.source_json.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GeoRepositoryError, match="GEO_SEARCH_PROVENANCE_INVALID"):
        repository.read(record.source_id)

    payload["search_provenance"]["selected_accession"] = "GSE23456"
    record.source_json.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GeoRepositoryError, match="GEO_SOURCE_CACHE_TAMPERED"):
        repository.read(record.source_id)


def test_repository_rejects_cache_tampering_and_does_not_overwrite_same_url(tmp_path: Path) -> None:
    source, candidate, selection, raw_path = _fixture(tmp_path)
    repository = GeoRepository(tmp_path / "sources")
    counts = pd.DataFrame({"GSM1": [1], "GSM2": [2], "GSM3": [3], "GSM4": [4]}, index=["G1"])
    metadata = pd.DataFrame(
        {"condition": ["A", "A", "B", "B"]}, index=["GSM1", "GSM2", "GSM3", "GSM4"]
    )
    first = repository.publish(source, candidate, selection, raw_path, counts, metadata)
    first.raw_path.write_bytes(b"tampered")

    with pytest.raises(GeoRepositoryError, match="GEO_SOURCE_CACHE_TAMPERED"):
        repository.read(first.source_id)

    raw_path.write_bytes(b"new bytes")
    selection = selection.model_copy(
        update={"raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()}
    )
    second = repository.publish(source, candidate, selection, raw_path, counts, metadata)
    assert second.source_id != first.source_id
    assert first.source_json.exists()


def test_shared_dataset_service_imports_standard_geo_projection_and_rejects_stale_revision(
    tmp_path: Path,
) -> None:
    source, candidate, selection, raw_path = _fixture(tmp_path)
    repository = GeoRepository(tmp_path / "sources")
    counts = pd.DataFrame(
        {"GSM1": [1], "GSM2": [2], "GSM3": [3], "GSM4": [4]}, index=["G1"]
    )
    metadata = pd.DataFrame(
        {"condition": ["A", "A", "B", "B"]},
        index=["GSM1", "GSM2", "GSM3", "GSM4"],
    )
    dataset = NormalizedDataset(
        counts=counts,
        metadata=metadata,
        raw_sha256=selection.raw_sha256,
        selection=selection,
        excluded_samples=(),
    )

    dataset_id = DatasetImportService(
        repository=DatasetRepository(tmp_path / "datasets")
    ).import_normalized(dataset)

    assert dataset_id
    assert len(list((tmp_path / "datasets").iterdir())) == 1
    digest = selection_hash(selection.raw_sha256, selection.model_dump(mode="json"))
    record = repository.publish(source, candidate, selection, raw_path, counts, metadata)
    assert record.selection_hash == digest
    with pytest.raises(GeoRepositoryError, match="SOURCE_SELECTION_CONFLICT"):
        repository.assert_selection_current(
            record.source_id,
            revision=selection.revision + 1,
            raw_sha256=selection.raw_sha256,
            selection=selection.model_dump(mode="json"),
        )
