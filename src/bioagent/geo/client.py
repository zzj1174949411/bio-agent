"""Read-only GEO family metadata discovery and deterministic file classification."""

from __future__ import annotations

import http.client
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx

from bioagent.geo.models import (
    Compression,
    DataKind,
    GeoCandidate,
    GeoField,
    GeoSample,
    GeoSource,
)
from bioagent.geo.transport import GeoTransport, GeoTransportError

_ACCESSION = re.compile(r"GSE[1-9][0-9]*")
_MAX_METADATA_BYTES = 10 * 1024 * 1024
_SUPPORTED_SUFFIXES = (".csv", ".tsv", ".txt")
_NORMALIZED_TERMS = ("tpm", "fpkm", "rpkm", "normalized", "series matrix", "microarray")
_FASTQ_TERMS = ("fastq", "fq", "sra")
_KIND_ORDER = {
    DataKind.RAW_COUNTS: 0,
    DataKind.UNKNOWN: 1,
    DataKind.NORMALIZED: 2,
    DataKind.UNSUPPORTED: 3,
}


class GeoDiscoveryError(ValueError):
    """Stable, non-sensitive GEO discovery failure."""


def normalize_accession(value: str) -> str:
    accession = value.strip().upper()
    if _ACCESSION.fullmatch(accession) is None:
        raise ValueError("GEO_ACCESSION_INVALID")
    return accession


class GeoClient:
    """Fetch only metadata; no candidate URL is downloaded at this boundary."""

    def __init__(self, http_client: httpx.Client | GeoTransport) -> None:
        self._http_client = http_client

    def _get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> httpx.Response:
        if isinstance(self._http_client, GeoTransport):
            return self._http_client.get(url, params=params, headers=headers)
        return self._http_client.get(url, params=params, headers=headers)

    def discover(self, accession: str) -> GeoSource:
        normalized = normalize_accession(accession)
        soft = self._fetch_soft(normalized)
        catalog = self._fetch_counts_catalog(normalized)
        return _build_source(normalized, soft, catalog)

    def _fetch_soft(self, accession: str) -> str:
        response = self._get(
            "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi",
            params={"acc": accession, "targ": "all", "form": "text", "view": "quick"},
            headers={"Accept": "text/plain"},
        )
        try:
            if response.status_code == 404:
                raise GeoDiscoveryError("GEO_NOT_FOUND")
            if response.status_code >= 400:
                raise GeoDiscoveryError("GEO_DISCOVERY_FAILED")
            return _decode_metadata(response, "GEO_SOFT_INVALID")
        finally:
            response.close()

    def _fetch_counts_catalog(self, accession: str) -> tuple[dict[str, Any], ...]:
        """Read NCBI's metadata catalog, never construct a candidate download URL."""

        response = self._get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "gds", "term": f"{accession}[ACCN]", "retmode": "json"},
            headers={"Accept": "application/json"},
        )
        try:
            if response.status_code >= 400:
                return ()
            payload = json.loads(_read_metadata(response))
        except ValueError as error:
            if isinstance(error, GeoDiscoveryError):
                raise
            raise GeoDiscoveryError("GEO_CATALOG_INVALID") from error
        finally:
            response.close()
        if not isinstance(payload, dict):
            raise GeoDiscoveryError("GEO_CATALOG_INVALID")
        # The optional catalog can return an official eutils error instead of records.
        # It must not prevent discovery of the submitter's SOFT supplementary files.
        if "records" not in payload and (
            "error" in payload or isinstance(payload.get("esummaryresult"), list)
        ):
            return ()
        records = payload.get("records", ())
        if not isinstance(records, list):
            raise GeoDiscoveryError("GEO_CATALOG_INVALID")
        return tuple(record for record in records if isinstance(record, dict))


def _decode_metadata(response: httpx.Response, error_code: str) -> str:
    try:
        return _read_metadata(response).decode("utf-8")
    except UnicodeDecodeError as error:
        raise GeoDiscoveryError(error_code) from error


def _read_metadata(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_METADATA_BYTES:
                raise GeoDiscoveryError("GEO_METADATA_TOO_LARGE")
        except ValueError as error:
            raise GeoDiscoveryError("GEO_METADATA_TOO_LARGE") from error
    body = bytearray()
    try:
        for block in response.iter_bytes():
            if len(body) + len(block) > _MAX_METADATA_BYTES:
                raise GeoDiscoveryError("GEO_METADATA_TOO_LARGE")
            body.extend(block)
    except (httpx.TimeoutException, TimeoutError) as error:
        raise GeoTransportError("DOWNLOAD_TIMEOUT") from error
    except (httpx.HTTPError, OSError, http.client.HTTPException) as error:
        raise GeoTransportError("DOWNLOAD_NETWORK_ERROR") from error
    return bytes(body)


def _build_source(
    accession: str,
    soft: str,
    catalog: tuple[dict[str, Any], ...],
) -> GeoSource:
    series, samples = _parse_soft(soft)
    if series is None:
        raise GeoDiscoveryError("GEO_NOT_FOUND")
    source_id = uuid4()
    source_fields = _as_fields(series["fields"])
    organisms = _unique_values(
        _values_for(source_fields, "Series_organism")
        + tuple(sample.organism for sample in samples if sample.organism is not None)
    )
    platforms = _unique_values(
        _values_for(source_fields, "Series_platform_id")
        + tuple(sample.platform for sample in samples if sample.platform is not None)
    )
    candidates = _classify_candidates(
        source_id,
        accession,
        _values_for(source_fields, "Series_supplementary_file"),
        catalog,
    )
    importable = tuple(
        candidate
        for candidate in candidates
        if candidate.data_kind in {DataKind.RAW_COUNTS, DataKind.UNKNOWN}
    )
    warnings: list[str] = []
    if len(organisms) > 1:
        warnings.append("GEO_MULTIPLE_ORGANISMS")
    if len(platforms) > 1:
        warnings.append("GEO_MULTIPLE_PLATFORMS")
    reasons: tuple[str, ...] = ()
    error_code: str | None = None
    if not importable:
        error_code = "GEO_NO_SUPPORTED_COUNTS"
        reasons = tuple(
            f"{candidate.file_name}: {candidate.data_kind.value}" for candidate in candidates
        ) or ("No supplementary or NCBI-generated count matrix was recorded.",)
    return GeoSource(
        id=source_id,
        accession=accession,
        title=_first_value(source_fields, "Series_title"),
        organisms=organisms,
        platforms=platforms,
        samples=samples,
        candidates=candidates,
        retrieved_at=datetime.now(UTC),
        fields=source_fields,
        warnings=tuple(warnings),
        error_code=error_code,
        reasons=reasons,
    )


def _parse_soft(soft: str) -> tuple[dict[str, object] | None, tuple[GeoSample, ...]]:
    entities: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw_line in soft.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("^"):
            name, value = _label_value(line[1:])
            if name not in {"SERIES", "SAMPLE", "PLATFORM"}:
                raise GeoDiscoveryError("GEO_SOFT_INVALID")
            current = {"entity": name, "accession": value, "fields": []}
            entities.append(current)
            continue
        if line.startswith("!"):
            if current is None:
                raise GeoDiscoveryError("GEO_SOFT_INVALID")
            name, value = _label_value(line[1:])
            fields = current["fields"]
            assert isinstance(fields, list)
            fields.append((name, value))
            continue
        if current is None:
            raise GeoDiscoveryError("GEO_SOFT_INVALID")
    series = next((entity for entity in entities if entity["entity"] == "SERIES"), None)
    if series is not None and not isinstance(series["accession"], str):
        raise GeoDiscoveryError("GEO_SOFT_INVALID")
    samples = tuple(_to_sample(entity) for entity in entities if entity["entity"] == "SAMPLE")
    return series, samples


def _label_value(line: str) -> tuple[str, str]:
    if " = " not in line:
        raise GeoDiscoveryError("GEO_SOFT_INVALID")
    name, value = line.split(" = ", maxsplit=1)
    if not name:
        raise GeoDiscoveryError("GEO_SOFT_INVALID")
    return name, value


def _to_sample(entity: dict[str, object]) -> GeoSample:
    fields = _as_fields(entity["fields"])
    accession = _first_value(fields, "Sample_geo_accession") or str(entity["accession"])
    try:
        return GeoSample(
            accession=accession,
            title=_first_value(fields, "Sample_title"),
            organism=_first_prefix_value(fields, "Sample_organism"),
            platform=_first_value(fields, "Sample_platform_id"),
            characteristics=tuple(
                field for field in fields if field.name.startswith("Sample_characteristics")
            ),
            fields=fields,
        )
    except ValueError as error:
        raise GeoDiscoveryError("GEO_SOFT_INVALID") from error


def _as_fields(raw_fields: object) -> tuple[GeoField, ...]:
    if not isinstance(raw_fields, list):
        raise GeoDiscoveryError("GEO_SOFT_INVALID")
    return tuple(GeoField(name=name, value=value, origin="SOFT") for name, value in raw_fields)


def _values_for(fields: tuple[GeoField, ...], name: str) -> tuple[str, ...]:
    return tuple(field.value for field in fields if field.name == name)


def _first_value(fields: tuple[GeoField, ...], name: str) -> str | None:
    values = _values_for(fields, name)
    return values[0] if values else None


def _first_prefix_value(fields: tuple[GeoField, ...], prefix: str) -> str | None:
    return next((field.value for field in fields if field.name.startswith(prefix)), None)


def _unique_values(values: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _classify_candidates(
    source_id: UUID,
    accession: str,
    supplementary_urls: tuple[str, ...],
    catalog: tuple[dict[str, Any], ...],
) -> tuple[GeoCandidate, ...]:
    records: list[tuple[str, str, int | None, tuple[str, ...]]] = []
    for url in supplementary_urls:
        file_name = _file_name(url)
        records.append((url, file_name, None, (f"SOFT supplementary file: {file_name}",)))
    for record in catalog:
        catalog_url = record.get("url")
        catalog_file_name = record.get("file_name")
        evidence = record.get("evidence")
        size_bytes = record.get("size_bytes")
        if (
            not isinstance(catalog_url, str)
            or not isinstance(catalog_file_name, str)
            or not isinstance(evidence, str)
        ):
            continue
        normalized_size = size_bytes if isinstance(size_bytes, int) else None
        records.append((catalog_url, catalog_file_name, normalized_size, (evidence,)))
    candidates = tuple(
        _candidate(source_id, accession, url, file_name, size_bytes, evidence)
        for url, file_name, size_bytes, evidence in records
    )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                _KIND_ORDER[candidate.data_kind],
                candidate.file_name.casefold(),
                candidate.url,
            ),
        )
    )


def _file_name(url: str) -> str:
    parsed = urlsplit(url)
    query_file = parse_qs(parsed.query).get("file", ())
    if query_file:
        return query_file[0]
    return PurePosixPath(parsed.path).name or "unknown"


def _candidate(
    source_id: UUID,
    accession: str,
    url: str,
    file_name: str,
    size_bytes: int | None,
    evidence: tuple[str, ...],
) -> GeoCandidate:
    kind = _classify(file_name, evidence)
    return GeoCandidate(
        id=uuid4(),
        source_id=source_id,
        accession=accession,
        url=url,
        file_name=file_name,
        size_bytes=size_bytes,
        data_kind=kind,
        evidence=evidence,
        compression=Compression.GZIP if file_name.casefold().endswith(".gz") else Compression.NONE,
    )


def _classify(file_name: str, evidence: tuple[str, ...]) -> DataKind:
    lower_name = file_name.casefold()
    lower_evidence = " ".join(evidence).casefold()
    suffix_name = lower_name[:-3] if lower_name.endswith(".gz") else lower_name
    if not suffix_name.endswith(_SUPPORTED_SUFFIXES):
        return DataKind.UNSUPPORTED
    if any(term in lower_name or term in lower_evidence for term in _FASTQ_TERMS):
        return DataKind.UNSUPPORTED
    if "annotation" in lower_name or "annotation" in lower_evidence:
        return DataKind.UNSUPPORTED
    if any(term in lower_name or term in lower_evidence for term in _NORMALIZED_TERMS):
        return DataKind.NORMALIZED
    if "ncbi-generated rna-seq raw counts matrix" in lower_evidence:
        return DataKind.RAW_COUNTS
    return DataKind.UNKNOWN
