import ssl
from collections.abc import Callable

import httpx
import pytest

from bioagent.geo.transport import (
    GeoTransport,
    GeoTransportError,
    canonicalize_url,
)

PUBLIC_IP = "93.184.216.34"


def test_canonicalizer_converts_official_http_and_ftp_to_https() -> None:
    assert canonicalize_url("http://www.ncbi.nlm.nih.gov/geo/file.tsv") == (
        "https://www.ncbi.nlm.nih.gov/geo/file.tsv"
    )
    assert canonicalize_url("ftp://ftp.ncbi.nlm.nih.gov/geo/file.tsv") == (
        "https://ftp.ncbi.nlm.nih.gov/geo/file.tsv"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@www.ncbi.nlm.nih.gov/file.tsv",
        "https://www.ncbi.nlm.nih.gov:8443/file.tsv",
        "https://example.test/file.tsv",
        "file:///C:/secret.tsv",
    ],
)
def test_canonicalizer_rejects_unsafe_url_forms(url: str) -> None:
    with pytest.raises(GeoTransportError, match="^DOWNLOAD_HOST_REJECTED$"):
        canonicalize_url(url)


class FakeConnector:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def __call__(
        self,
        url: str,
        addresses: tuple[str, ...],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        self.calls.append((url, addresses))
        response = self.responses.pop(0)
        response.request = httpx.Request("GET", url)
        return response


def _transport(
    connector: FakeConnector,
    resolver: Callable[[str], tuple[str, ...]],
) -> GeoTransport:
    return GeoTransport(connector=connector, resolver=resolver, rate_limiter=None)


def test_transport_resolves_each_request_and_follows_same_host_redirect() -> None:
    connector = FakeConnector(
        [
            httpx.Response(302, headers={"Location": "/next.tsv"}),
            httpx.Response(200, content=b"counts"),
        ]
    )
    transport = _transport(connector, lambda host: (PUBLIC_IP,))

    response = transport.get("https://www.ncbi.nlm.nih.gov/start.tsv")

    assert response.status_code == 200
    assert [call[0] for call in connector.calls] == [
        "https://www.ncbi.nlm.nih.gov/start.tsv",
        "https://www.ncbi.nlm.nih.gov/next.tsv",
    ]
    assert all(addresses == (PUBLIC_IP,) for _, addresses in connector.calls)


def test_transport_rejects_cross_host_redirect() -> None:
    connector = FakeConnector(
        [httpx.Response(302, headers={"Location": "https://ftp.ncbi.nlm.nih.gov/next.tsv"})]
    )
    transport = _transport(connector, lambda host: (PUBLIC_IP,))

    with pytest.raises(GeoTransportError, match="^DOWNLOAD_HOST_REJECTED$"):
        transport.get("https://www.ncbi.nlm.nih.gov/start.tsv")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.1.1", "::1", "fc00::1"])
def test_transport_rejects_non_public_resolved_address(address: str) -> None:
    connector = FakeConnector([httpx.Response(200, content=b"counts")])
    transport = _transport(connector, lambda host: (address,))

    with pytest.raises(GeoTransportError, match="^DOWNLOAD_HOST_REJECTED$"):
        transport.get("https://www.ncbi.nlm.nih.gov/start.tsv")

    assert not connector.calls


def test_transport_rejects_dns_rebinding_between_redirect_hops() -> None:
    connector = FakeConnector(
        [httpx.Response(302, headers={"Location": "/next.tsv"})]
    )
    addresses = iter([(PUBLIC_IP,), ("93.184.216.35",)])
    transport = _transport(connector, lambda host: next(addresses))

    with pytest.raises(GeoTransportError, match="^DOWNLOAD_HOST_REJECTED$"):
        transport.get("https://www.ncbi.nlm.nih.gov/start.tsv")


def test_transport_limits_redirect_hops() -> None:
    connector = FakeConnector(
        [
            httpx.Response(302, headers={"Location": "/one.tsv"}),
            httpx.Response(302, headers={"Location": "/two.tsv"}),
            httpx.Response(302, headers={"Location": "/three.tsv"}),
            httpx.Response(200, content=b"too late"),
        ]
    )
    transport = GeoTransport(
        connector=connector,
        resolver=lambda host: (PUBLIC_IP,),
        rate_limiter=None,
        max_redirects=2,
    )

    with pytest.raises(GeoTransportError, match="^DOWNLOAD_TOO_MANY_REDIRECTS$"):
        transport.get("https://www.ncbi.nlm.nih.gov/start.tsv")


def test_transport_surfaces_certificate_failure_without_fallback() -> None:
    def connector(
        url: str,
        addresses: tuple[str, ...],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        raise ssl.SSLCertVerificationError("synthetic certificate failure")

    transport = _transport(connector, lambda host: (PUBLIC_IP,))

    with pytest.raises(GeoTransportError, match="^DOWNLOAD_TLS_ERROR$"):
        transport.get("https://www.ncbi.nlm.nih.gov/start.tsv")
