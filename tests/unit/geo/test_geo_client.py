import json
from pathlib import Path

import httpx
import pytest

from bioagent.geo.client import (
    GeoClient,
    GeoDiscoveryError,
    normalize_accession,
)
from bioagent.geo.models import DataKind

FIXTURES = Path("tests/fixtures/geo")


def _client(
    soft: str | None = None,
    catalog: dict[str, object] | None = None,
    soft_status: int = 200,
) -> GeoClient:
    soft_body = (FIXTURES / "family.soft").read_text(encoding="utf-8") if soft is None else soft
    catalog_body = (
        json.loads((FIXTURES / "counts_catalog.json").read_text(encoding="utf-8"))
        if catalog is None
        else catalog
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.ncbi.nlm.nih.gov":
            return httpx.Response(soft_status, text=soft_body, request=request)
        if request.url.host == "eutils.ncbi.nlm.nih.gov":
            return httpx.Response(200, json=catalog_body, request=request)
        raise AssertionError(f"unexpected outbound request: {request.url!s}")

    return GeoClient(httpx.Client(transport=httpx.MockTransport(handler)))


def test_accession_normalizes_without_accepting_urls() -> None:
    assert normalize_accession(" gse12345 ") == "GSE12345"
    for invalid in ("https://example.test/GSE12345", "GSM12345", "GSE0", "GSE12 GSE13"):
        with pytest.raises(ValueError, match="^GEO_ACCESSION_INVALID$"):
            normalize_accession(invalid)


def test_discover_parses_soft_metadata_preserving_duplicate_characteristics() -> None:
    source = _client().discover("gse12345")

    assert source.accession == "GSE12345"
    assert source.title == "Synthetic bulk RNA-seq study"
    assert source.organisms == ("Homo sapiens",)
    assert source.platforms == ("GPL99999",)
    assert [sample.accession for sample in source.samples] == [
        "GSM10001",
        "GSM10002",
        "GSM10003",
        "GSM10004",
    ]
    assert [field.value for field in source.samples[0].characteristics] == [
        "condition: Control",
        "tissue: liver",
    ]
    assert all(field.origin == "SOFT" for field in source.samples[0].characteristics)


def test_discover_classifies_and_deterministically_orders_candidates() -> None:
    source = _client().discover("GSE12345")
    found = {candidate.file_name: candidate for candidate in source.candidates}

    assert found["GSE12345_raw_counts_GRCh38.tsv.gz"].data_kind is DataKind.RAW_COUNTS
    assert found["GSE12345_normalized_counts_GRCh38.tsv.gz"].data_kind is DataKind.NORMALIZED
    assert found["GSE12345_gene_annotation.tsv.gz"].data_kind is DataKind.UNSUPPORTED
    assert found["GSE12345_submitter_raw_counts.tsv.gz"].data_kind is DataKind.UNKNOWN
    assert found["GSE12345_TPM.tsv.gz"].data_kind is DataKind.NORMALIZED
    assert found["GSE12345_reads.fastq.gz"].data_kind is DataKind.UNSUPPORTED
    assert found["GSE12345_count_like.txt"].data_kind is DataKind.UNKNOWN
    assert "count" in found["GSE12345_count_like.txt"].evidence[0].lower()
    assert found["GSE12345_count_like.txt"].data_kind is not DataKind.RAW_COUNTS
    assert [candidate.data_kind for candidate in source.candidates] == sorted(
        (candidate.data_kind for candidate in source.candidates), key=lambda kind: {
            DataKind.RAW_COUNTS: 0,
            DataKind.UNKNOWN: 1,
            DataKind.NORMALIZED: 2,
            DataKind.UNSUPPORTED: 3,
        }[kind]
    )
    assert [candidate.file_name for candidate in source.importable_candidates] == [
        "GSE12345_raw_counts_GRCh38.tsv.gz",
        "GSE12345_count_like.txt",
        "GSE12345_submitter_raw_counts.tsv.gz",
    ]


def test_no_supported_candidate_has_stable_error_and_reasons() -> None:
    source = _client(
        catalog={"records": []},
        soft=(FIXTURES / "family.soft").read_text(encoding="utf-8").replace(
            "GSE12345_submitter_raw_counts.tsv.gz", "GSE12345_TPM_only.tsv.gz"
        ).replace("GSE12345_count_like.txt", "GSE12345_reads_only.fastq.gz"),
    ).discover("GSE12345")

    assert source.error_code == "GEO_NO_SUPPORTED_COUNTS"
    assert source.importable_candidates == ()
    assert source.reasons


@pytest.mark.parametrize(
    ("soft", "status", "message"),
    [
        ("", 404, "GEO_NOT_FOUND"),
        ("", 200, "GEO_NOT_FOUND"),
        ("not a SOFT record", 200, "GEO_SOFT_INVALID"),
        ("^BROKEN = GSE12345\n!Series_title = bad", 200, "GEO_SOFT_INVALID"),
    ],
)
def test_discover_reports_not_found_and_invalid_soft(
    soft: str,
    status: int,
    message: str,
) -> None:
    with pytest.raises(GeoDiscoveryError, match=f"^{message}$"):
        _client(soft=soft, soft_status=status).discover("GSE12345")


def test_discover_reports_mixed_species_and_platforms() -> None:
    source = _client(
        soft=(FIXTURES / "family.soft")
        .read_text(encoding="utf-8")
        .replace("Homo sapiens", "Mus musculus", 1)
        .replace("GPL99999", "GPL11111", 1),
    ).discover("GSE12345")

    assert "GEO_MULTIPLE_ORGANISMS" in source.warnings
    assert "GEO_MULTIPLE_PLATFORMS" in source.warnings
