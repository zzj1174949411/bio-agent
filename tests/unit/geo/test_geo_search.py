import json
from pathlib import Path

import httpx
import pytest

from bioagent.geo.search import _MAX_RESPONSE_BYTES, GeoSearchError, NcbiGeoCatalogProvider
from bioagent.retrieval.contracts import DatasetSearchQuery

FIXTURES = Path("tests/fixtures/geo")


@pytest.fixture
def provider() -> tuple[NcbiGeoCatalogProvider, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    esearch = json.loads((FIXTURES / "search_esearch.json").read_text(encoding="utf-8"))
    esummary = json.loads((FIXTURES / "search_esummary.json").read_text(encoding="utf-8"))

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json=esearch, request=request)
        if request.url.path.endswith("esummary.fcgi"):
            return httpx.Response(200, json=esummary, request=request)
        raise AssertionError(f"unexpected request: {request.url!s}")

    return NcbiGeoCatalogProvider(httpx.Client(transport=httpx.MockTransport(respond))), requests


def test_search_encodes_business_terms_filters_and_maps_deduplicated_hits(provider) -> None:
    catalog, requests = provider

    page = catalog.search(
        DatasetSearchQuery(
            text='brain [bad] "term"', organism="Homo sapiens", technology="RNA-seq"
        )
    )

    assert [item.source_id for item in page.items] == ["GSE12345", "GSE23456"]
    assert page.items[0].source_uri == "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345"
    assert page.items[0].analysis_readiness == "NEEDS_INSPECTION"
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "esearch.fcgi",
        "esummary.fcgi",
    ]
    params = dict(requests[0].url.params)
    assert params["db"] == "gds"
    assert params["retmode"] == "json"
    assert params["retstart"] == "0"
    assert params["retmax"] == "10"
    assert "gse[ETYP]" in params["term"]
    assert r"\[bad\]" in params["term"]
    assert dict(requests[1].url.params)["id"] == "100,200"


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(429), "GEO_SEARCH_RATE_LIMITED"),
        (httpx.Response(404), "GEO_SEARCH_NOT_FOUND"),
    ],
)
def test_search_maps_http_failures(response: httpx.Response, expected: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        response.request = request
        return response

    provider = NcbiGeoCatalogProvider(httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(GeoSearchError, match=f"^{expected}$"):
        provider.search(DatasetSearchQuery(text="brain"))


def test_search_rejects_malformed_oversized_timeout_and_empty_results() -> None:
    responses = iter(
        [
            httpx.Response(200, content=b"not json"),
            httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
            httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}}),
        ]
    )

    def respond(request: httpx.Request) -> httpx.Response:
        value = next(responses)
        value.request = request
        return value

    provider = NcbiGeoCatalogProvider(httpx.Client(transport=httpx.MockTransport(respond)))
    for expected in ("GEO_SEARCH_MALFORMED", "GEO_SEARCH_OVER_LIMIT", "GEO_SEARCH_NO_RESULTS"):
        with pytest.raises(GeoSearchError, match=f"^{expected}$"):
            provider.search(DatasetSearchQuery(text="brain"))

    class TimeoutTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("fixture timeout", request=request)

    with pytest.raises(GeoSearchError, match="^GEO_SEARCH_TIMEOUT$"):
        NcbiGeoCatalogProvider(httpx.Client(transport=TimeoutTransport())).search(
            DatasetSearchQuery(text="brain")
        )


def test_search_rejects_declared_or_chunked_oversized_bodies_before_full_read() -> None:
    class CountingStream(httpx.SyncByteStream):
        def __init__(self, chunks: int) -> None:
            self.chunks = chunks
            self.reads = 0

        def __iter__(self):
            for _ in range(self.chunks):
                self.reads += 1
                yield b"x" * (64 * 1024)

    declared = CountingStream(40)
    chunked = CountingStream(40)
    responses = iter(
        [
            httpx.Response(
                200,
                headers={"Content-Length": str(_MAX_RESPONSE_BYTES + 1)},
                stream=declared,
            ),
            httpx.Response(200, stream=chunked),
        ]
    )

    class Transport:
        def get(self, url: str, **_kwargs: object) -> httpx.Response:
            response = next(responses)
            response.request = httpx.Request("GET", url)
            return response

    provider = NcbiGeoCatalogProvider(Transport())
    with pytest.raises(GeoSearchError, match="^GEO_SEARCH_OVER_LIMIT$"):
        provider.search(DatasetSearchQuery(text="brain"))
    assert declared.reads == 0

    with pytest.raises(GeoSearchError, match="^GEO_SEARCH_OVER_LIMIT$"):
        provider.search(DatasetSearchQuery(text="brain"))
    assert chunked.reads == _MAX_RESPONSE_BYTES // (64 * 1024) + 1
    assert chunked.reads < 40
