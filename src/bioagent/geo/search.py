"""Bounded NCBI E-utilities GEO catalog provider."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

import httpx

from bioagent.geo.transport import GeoTransportError
from bioagent.retrieval.contracts import (
    AnalysisReadiness,
    DatasetSearchHit,
    DatasetSearchPage,
    DatasetSearchQuery,
    EvidenceRef,
)

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_RESULTS = 100


class GeoSearchError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SearchTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        timeout: float = 10.0,
    ) -> httpx.Response: ...


class NcbiGeoCatalogProvider:
    """Search only official catalog metadata; this class never discovers or downloads files."""

    def __init__(self, transport: SearchTransport, *, timeout: float = 10.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._transport = transport
        self._timeout = timeout

    def search(self, query: DatasetSearchQuery) -> DatasetSearchPage:
        offset = _offset(query.page_token)
        esearch = self._get_json(
            f"{_EUTILS}/esearch.fcgi",
            {
                "db": "gds",
                "term": _term(query),
                "retmode": "json",
                "retstart": offset,
                "retmax": query.page_size,
            },
        )
        result = esearch.get("esearchresult")
        if not isinstance(result, dict):
            raise GeoSearchError("GEO_SEARCH_MALFORMED")
        count = _positive_or_zero(result.get("count"))
        if count > _MAX_RESULTS:
            raise GeoSearchError("GEO_SEARCH_OVER_LIMIT")
        identifiers = result.get("idlist")
        if not isinstance(identifiers, list) or not all(
            isinstance(item, str) for item in identifiers
        ):
            raise GeoSearchError("GEO_SEARCH_MALFORMED")
        stable_ids = tuple(dict.fromkeys(identifiers))
        if not stable_ids:
            raise GeoSearchError("GEO_SEARCH_NO_RESULTS")
        summary = self._get_json(
            f"{_EUTILS}/esummary.fcgi",
            {
                "db": "gds",
                "id": ",".join(stable_ids),
                "retmode": "json",
                "version": "2.0",
            },
        )
        records = summary.get("result")
        if not isinstance(records, dict):
            raise GeoSearchError("GEO_SEARCH_MALFORMED")
        items = _items(records, stable_ids)
        if not items:
            raise GeoSearchError("GEO_SEARCH_NO_RESULTS")
        next_offset = offset + len(stable_ids)
        return DatasetSearchPage(
            items=items,
            total=count,
            next_page_token=str(next_offset) if next_offset < count else None,
        )

    def _get_json(self, url: str, params: Mapping[str, str | int]) -> dict[str, object]:
        try:
            response = self._transport.get(url, params=params, timeout=self._timeout)
        except GeoTransportError as error:
            raise GeoSearchError(_transport_code(error.code)) from error
        except (httpx.TimeoutException, TimeoutError) as error:
            raise GeoSearchError("GEO_SEARCH_TIMEOUT") from error
        except (httpx.HTTPError, OSError) as error:
            raise GeoSearchError("GEO_SEARCH_UNAVAILABLE") from error
        try:
            if response.status_code == 429:
                raise GeoSearchError("GEO_SEARCH_RATE_LIMITED")
            if response.status_code == 404:
                raise GeoSearchError("GEO_SEARCH_NOT_FOUND")
            if response.status_code < 200 or response.status_code >= 300:
                raise GeoSearchError("GEO_SEARCH_UNAVAILABLE")
            declared_size = response.headers.get("content-length")
            if declared_size is not None and _content_length_exceeds_limit(declared_size):
                raise GeoSearchError("GEO_SEARCH_OVER_LIMIT")
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise GeoSearchError("GEO_SEARCH_OVER_LIMIT")
                body.extend(chunk)
            parsed = json.loads(body)
        except GeoSearchError:
            raise
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise GeoSearchError("GEO_SEARCH_MALFORMED") from error
        finally:
            response.close()
        if not isinstance(parsed, dict):
            raise GeoSearchError("GEO_SEARCH_MALFORMED")
        return parsed


def _content_length_exceeds_limit(value: str) -> bool:
    try:
        size = int(value)
    except ValueError as error:
        raise GeoSearchError("GEO_SEARCH_MALFORMED") from error
    if size < 0:
        raise GeoSearchError("GEO_SEARCH_MALFORMED")
    return size > _MAX_RESPONSE_BYTES


def _offset(token: str | None) -> int:
    if token is None:
        return 0
    if not token.isascii() or not token.isdecimal():
        raise GeoSearchError("GEO_SEARCH_INVALID")
    value = int(token)
    if value < 0 or value >= _MAX_RESULTS:
        raise GeoSearchError("GEO_SEARCH_INVALID")
    return value


def _term(query: DatasetSearchQuery) -> str:
    terms = [f'"{_escape(query.text)}"', "gse[ETYP]"]
    for value in (query.organism, query.tissue, query.technology):
        if value is not None:
            terms.append(f'"{_escape(value)}"')
    return " AND ".join(terms)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("[", "\\[").replace("]", "\\]")


def _positive_or_zero(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise GeoSearchError("GEO_SEARCH_MALFORMED") from error
    if parsed < 0:
        raise GeoSearchError("GEO_SEARCH_MALFORMED")
    return parsed


def _items(
    records: dict[str, object], identifiers: tuple[str, ...]
) -> tuple[DatasetSearchHit, ...]:
    hits: list[DatasetSearchHit] = []
    seen: set[str] = set()
    for identifier in identifiers:
        raw = records.get(identifier)
        if not isinstance(raw, dict):
            continue
        accession = raw.get("accession")
        if not isinstance(accession, str) or not _valid_accession(accession) or accession in seen:
            continue
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        seen.add(accession)
        source_uri = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}"
        encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        evidence = EvidenceRef(
            provider="geo",
            source_id=accession,
            source_uri=source_uri,
            retrieved_at=datetime.now(UTC),
            content_sha256=sha256(encoded).hexdigest(),
        )
        hits.append(
            DatasetSearchHit(
                provider="geo",
                source_id=accession,
                title=title.strip(),
                summary=_optional_string(raw.get("summary")),
                organisms=_strings(raw.get("taxon")),
                platforms=_strings(raw.get("gpl")),
                sample_count=_count(raw.get("n_samples")),
                published_at=_optional_string(raw.get("PDAT")),
                source_uri=source_uri,
                evidence=evidence,
                analysis_readiness=AnalysisReadiness.NEEDS_INSPECTION,
            )
        )
    return tuple(hits)


def _valid_accession(value: str) -> bool:
    return len(value) > 3 and value.startswith("GSE") and value[3:].isdigit() and value[3] != "0"


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(item.strip() for item in value if item.strip())
    return ()


def _count(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _transport_code(code: str) -> str:
    if code == "DOWNLOAD_TIMEOUT":
        return "GEO_SEARCH_TIMEOUT"
    if code in {"DOWNLOAD_NETWORK_ERROR", "DOWNLOAD_DNS_FAILED", "DOWNLOAD_TLS_ERROR"}:
        return "GEO_SEARCH_UNAVAILABLE"
    return "GEO_SEARCH_INVALID"


__all__ = ["GeoSearchError", "NcbiGeoCatalogProvider"]
