"""DNS-pinned, allow-listed HTTPS transport for GEO metadata and files."""

from __future__ import annotations

import http.client
import inspect
import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

ALLOWED_GEO_HOSTS = frozenset(
    {"www.ncbi.nlm.nih.gov", "ftp.ncbi.nlm.nih.gov", "eutils.ncbi.nlm.nih.gov"}
)
_DEFAULT_PORT = 443
_MAX_REDIRECTS = 3

Resolver = Callable[[str], Sequence[str]]
Connector = Callable[..., httpx.Response]


class GeoTransportError(RuntimeError):
    """Stable transport errors safe to expose to the API/UI."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonicalize_url(url: str) -> str:
    """Accept only official NCBI URLs and normalize them to HTTPS port 443."""

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise GeoTransportError("DOWNLOAD_HOST_REJECTED") from error
    if (
        parsed.scheme.casefold() not in {"https", "http", "ftp"}
        or hostname is None
        or hostname.casefold() not in ALLOWED_GEO_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port != _DEFAULT_PORT)
        or parsed.fragment
    ):
        raise GeoTransportError("DOWNLOAD_HOST_REJECTED")
    normalized_host = hostname.casefold()
    return urlunsplit(
        ("https", normalized_host, parsed.path or "/", parsed.query, "")
    )


def _resolve_public(hostname: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(
            hostname,
            _DEFAULT_PORT,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise GeoTransportError("DOWNLOAD_DNS_FAILED") from error
    addresses = tuple(
        dict.fromkeys(info[4][0] for info in infos if isinstance(info[4][0], str))
    )
    return addresses


def _validate_public_addresses(addresses: Sequence[str]) -> tuple[str, ...]:
    if not addresses:
        raise GeoTransportError("DOWNLOAD_HOST_REJECTED")
    validated: list[str] = []
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address.split("%", maxsplit=1)[0])
        except ValueError as error:
            raise GeoTransportError("DOWNLOAD_HOST_REJECTED") from error
        # is_global excludes loopback, private, link-local, unspecified,
        # multicast and reserved IPv4/IPv6 ranges.
        if not parsed.is_global:
            raise GeoTransportError("DOWNLOAD_HOST_REJECTED")
        validated.append(str(parsed))
    return tuple(dict.fromkeys(validated))


class TokenRateLimiter:
    """A process-wide spacing limiter; callers may inject a no-op in tests."""

    def __init__(self, requests_per_second: float = 2.0) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        now = time.monotonic()
        with self._lock:
            delay = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if delay:
            time.sleep(delay)


GLOBAL_GEO_RATE_LIMITER = TokenRateLimiter(2.0)


class _SocketConnector:
    """Connect directly to a validated IP while retaining TLS hostname checks."""

    def __call__(
        self,
        method: str,
        url: str,
        addresses: tuple[str, ...],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        parsed = urlsplit(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        context = ssl.create_default_context()
        last_error: OSError | None = None
        for address in addresses:
            raw: socket.socket | None = None
            tls: ssl.SSLSocket | None = None
            keep_open = False
            try:
                raw = socket.create_connection((address, _DEFAULT_PORT), timeout=timeout)
                tls = context.wrap_socket(raw, server_hostname=parsed.hostname)
                request_headers = {
                    "Host": parsed.hostname or "",
                    "Connection": "close",
                    **headers,
                }
                encoded_headers = "".join(
                    f"{name}: {value}\r\n" for name, value in request_headers.items()
                )
                tls.sendall(
                    f"{method} {path} HTTP/1.1\r\n{encoded_headers}\r\n".encode("ascii")
                )
                response = http.client.HTTPResponse(tls)
                response.begin()
                response_headers = {
                    name: value for name, value in response.getheaders()
                }
                assert raw is not None
                result = httpx.Response(
                    response.status,
                    headers=response_headers,
                    stream=_SocketResponseStream(response, tls, raw),
                    request=httpx.Request(method, url),
                )
                keep_open = True
                return result
            except ssl.SSLCertVerificationError as error:
                raise GeoTransportError("DOWNLOAD_TLS_ERROR") from error
            except (OSError, ssl.SSLError) as error:
                last_error = error
                continue
            finally:
                if not keep_open:
                    if tls is not None:
                        tls.close()
                    elif raw is not None:
                        raw.close()
        if isinstance(last_error, TimeoutError):
            raise GeoTransportError("DOWNLOAD_TIMEOUT") from last_error
        raise GeoTransportError("DOWNLOAD_NETWORK_ERROR") from last_error


class _SocketResponseStream(httpx.SyncByteStream):
    def __init__(
        self,
        response: http.client.HTTPResponse,
        tls: ssl.SSLSocket,
        raw: socket.socket,
    ) -> None:
        self._response = response
        self._tls = tls
        self._raw = raw

    def __iter__(self) -> Iterator[bytes]:
        while True:
            block = self._response.read(64 * 1024)
            if not block:
                break
            yield block

    def close(self) -> None:
        self._response.close()
        self._tls.close()
        self._raw.close()


@dataclass(frozen=True)
class _Resolution:
    host: str
    addresses: tuple[str, ...]


class GeoTransport:
    """Manual redirecting transport that binds each request to checked IPs."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        connector: Connector | None = None,
        rate_limiter: TokenRateLimiter | None = GLOBAL_GEO_RATE_LIMITER,
        max_redirects: int = _MAX_REDIRECTS,
    ) -> None:
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        self._resolver = resolver or _resolve_public
        self._connector: Connector = connector or _SocketConnector()
        self._rate_limiter = rate_limiter
        self._max_redirects = max_redirects
        self._connector_accepts_method = self._accepts_method(self._connector)

    @staticmethod
    def _accepts_method(connector: Connector) -> bool:
        try:
            parameters = inspect.signature(connector).parameters.values()
        except (TypeError, ValueError):
            return True
        positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        ]
        return len(positional) >= 5 or any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters
        )

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
    ) -> httpx.Response:
        return self.request("GET", url, params=params, headers=headers, timeout=timeout)

    def head(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
    ) -> httpx.Response:
        return self.request("HEAD", url, params=params, headers=headers, timeout=timeout)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
    ) -> httpx.Response:
        current = _append_params(url, params)
        request_headers = {"User-Agent": "bio-agent/0.1 GEO client", **dict(headers or {})}
        resolutions: dict[str, _Resolution] = {}
        for redirect_count in range(self._max_redirects + 1):
            current = canonicalize_url(current)
            parsed = urlsplit(current)
            hostname = parsed.hostname
            assert hostname is not None
            resolution = self._resolve_once(hostname, resolutions)
            if self._rate_limiter is not None:
                self._rate_limiter.acquire()
            try:
                response = self._call_connector(
                    method,
                    current,
                    resolution.addresses,
                    request_headers,
                    timeout,
                )
            except GeoTransportError:
                raise
            except ssl.SSLCertVerificationError as error:
                raise GeoTransportError("DOWNLOAD_TLS_ERROR") from error
            except (httpx.TimeoutException, TimeoutError) as error:
                raise GeoTransportError("DOWNLOAD_TIMEOUT") from error
            except (httpx.HTTPError, OSError) as error:
                raise GeoTransportError("DOWNLOAD_NETWORK_ERROR") from error
            location = response.headers.get("location")
            if response.status_code not in {301, 302, 303, 307, 308} or location is None:
                return response
            if redirect_count >= self._max_redirects:
                raise GeoTransportError("DOWNLOAD_TOO_MANY_REDIRECTS")
            redirected = canonicalize_url(urljoin(current, location))
            redirected_host = urlsplit(redirected).hostname
            if redirected_host != hostname:
                response.close()
                raise GeoTransportError("DOWNLOAD_HOST_REJECTED")
            response.close()
            current = redirected
        raise GeoTransportError("DOWNLOAD_TOO_MANY_REDIRECTS")

    def _resolve_once(
        self,
        hostname: str,
        resolutions: dict[str, _Resolution],
    ) -> _Resolution:
        try:
            addresses = _validate_public_addresses(self._resolver(hostname))
        except GeoTransportError:
            raise
        except (OSError, ValueError) as error:
            raise GeoTransportError("DOWNLOAD_DNS_FAILED") from error
        previous = resolutions.get(hostname)
        if previous is not None and previous.addresses != addresses:
            raise GeoTransportError("DOWNLOAD_HOST_REJECTED")
        resolution = _Resolution(hostname, addresses)
        resolutions[hostname] = resolution
        return resolution

    def _call_connector(
        self,
        method: str,
        url: str,
        addresses: tuple[str, ...],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        if self._connector_accepts_method:
            return self._connector(method, url, addresses, headers, timeout)
        return self._connector(url, addresses, headers, timeout)


def _append_params(url: str, params: Mapping[str, str | int] | None) -> str:
    if not params:
        return url
    parsed = urlsplit(url)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend((key, str(value)) for key, value in params.items())
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )
