"""Streaming GEO downloads, gzip expansion and atomic evidence publication."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol
from uuid import uuid4

import httpx

from bioagent.config import Settings
from bioagent.geo.transport import GeoTransport, GeoTransportError


class DownloadLimitError(RuntimeError):
    """A configured compressed or expanded byte limit was exceeded."""

    def __init__(self, code: str = "DOWNLOAD_TOO_LARGE") -> None:
        self.code = code
        super().__init__(code)


class GeoDownloadError(RuntimeError):
    """Stable download failure that is safe to expose to a caller."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DownloadTransport(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    bytes_downloaded: int
    content_type: str | None
    etag: str | None
    last_modified: str | None


def checked_total(current: int, block: bytes, maximum: int) -> int:
    result = current + len(block)
    if result > maximum:
        raise DownloadLimitError()
    return result


def _reject_path_traversal(path: Path) -> None:
    if any(part == ".." for part in path.parts):
        raise GeoDownloadError("DOWNLOAD_PATH_REJECTED")


def _ensure_destination(target: Path, root: Path | None) -> tuple[Path, Path, Path]:
    _reject_path_traversal(target)
    if os.path.lexists(target):
        raise GeoDownloadError("DOWNLOAD_TARGET_EXISTS")
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise GeoDownloadError("DOWNLOAD_PATH_REJECTED")
    resolved_parent = parent.resolve()
    resolved_root = (root or resolved_parent).resolve()
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as error:
        raise GeoDownloadError("DOWNLOAD_PATH_REJECTED") from error
    return resolved_parent / target.name, resolved_parent, resolved_root


def _new_part(parent: Path) -> Path:
    return parent / f".{uuid4().hex}.part"


def _publish_without_overwrite(part: Path, target: Path) -> None:
    if os.path.lexists(target):
        raise GeoDownloadError("DOWNLOAD_TARGET_EXISTS")
    try:
        os.link(part, target)
    except FileExistsError as error:
        raise GeoDownloadError("DOWNLOAD_TARGET_EXISTS") from error
    except OSError as error:
        raise GeoDownloadError("DOWNLOAD_PUBLISH_FAILED") from error
    finally:
        part.unlink(missing_ok=True)
    try:
        directory_fd = os.open(target.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


def _validate_regular_source(source: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise GeoDownloadError("DOWNLOAD_SOURCE_INVALID")


def expand_gzip(
    source: Path,
    destination: Path,
    max_bytes: int,
    *,
    max_compressed_bytes: int = 100 * 1024 * 1024,
    root: Path | None = None,
) -> Path:
    """Expand exactly one gzip stream without overwriting evidence."""

    source = Path(source)
    destination = Path(destination)
    _validate_regular_source(source)
    destination, _, _ = _ensure_destination(destination, root)
    if source.stat().st_size > max_compressed_bytes:
        raise DownloadLimitError()
    part = _new_part(destination.parent)
    total = 0
    try:
        with gzip.open(source, "rb") as input_stream, part.open("xb") as output_stream:
            while True:
                block = input_stream.read(64 * 1024)
                if not block:
                    break
                total = checked_total(total, block, max_bytes)
                output_stream.write(block)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        _publish_without_overwrite(part, destination)
        return destination
    except DownloadLimitError:
        part.unlink(missing_ok=True)
        raise
    except GeoDownloadError:
        part.unlink(missing_ok=True)
        raise
    except (gzip.BadGzipFile, EOFError, OSError) as error:
        part.unlink(missing_ok=True)
        raise GeoDownloadError("DOWNLOAD_INVALID_GZIP") from error
    finally:
        part.unlink(missing_ok=True)


class GeoDownloader:
    """Download a single source into an existing, controlled directory."""

    def __init__(
        self,
        transport: DownloadTransport | GeoTransport,
        *,
        settings: Settings | None = None,
        root: Path | None = None,
        max_file_bytes: int | None = None,
        max_total_bytes: int | None = None,
        max_retries: int | None = None,
        max_redirects: int | None = None,
        connect_timeout_seconds: float | None = None,
        total_timeout_seconds: float | None = None,
        disk_reserve_bytes: int | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        policy = settings or Settings.model_construct()
        self._transport = transport
        self._root = root
        self._max_file_bytes = max_file_bytes or policy.geo_max_file_bytes
        self._max_total_bytes = max_total_bytes or policy.geo_max_total_bytes
        self._max_retries = max_retries if max_retries is not None else policy.geo_max_retries
        self._max_redirects = (
            max_redirects if max_redirects is not None else policy.geo_max_redirects
        )
        self._connect_timeout = connect_timeout_seconds or policy.geo_connect_timeout_seconds
        self._total_timeout = total_timeout_seconds or policy.geo_download_timeout_seconds
        self._disk_reserve_bytes = (
            disk_reserve_bytes
            if disk_reserve_bytes is not None
            else policy.geo_disk_reserve_bytes
        )
        self._sleeper = sleeper
        self._clock = clock
        self._reservation_lock = threading.Lock()
        self._reserved_total = 0
        self._downloaded_total = 0

    def download(
        self,
        url: str,
        destination: Path,
        *,
        expected_sha256: str | None = None,
        cancel_event: Event | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> DownloadResult:
        target, parent, disk_root = _ensure_destination(Path(destination), self._root)
        if shutil.disk_usage(disk_root).free < self._disk_reserve_bytes:
            raise GeoDownloadError("DOWNLOAD_DISK_FULL")
        self._reserve_total()
        reservation_active = True
        part = _new_part(parent)
        deadline = self._clock() + self._total_timeout
        try:
            response = self._request_with_retries(url, deadline, cancel_event)
            self._check_content_length(response)
            digest = hashlib.sha256()
            total = 0
            try:
                with part.open("xb") as output_stream:
                    for block in response.iter_bytes(64 * 1024):
                        self._check_cancel(cancel_event)
                        if self._clock() > deadline:
                            raise GeoDownloadError("DOWNLOAD_TIMEOUT")
                        total = checked_total(total, block, self._max_file_bytes)
                        digest.update(block)
                        output_stream.write(block)
                        if progress is not None:
                            progress(total)
                    output_stream.flush()
                    os.fsync(output_stream.fileno())
            finally:
                response.close()
            actual_hash = digest.hexdigest()
            if expected_sha256 is not None and actual_hash != expected_sha256.lower():
                raise GeoDownloadError("SOURCE_CHANGED")
            _publish_without_overwrite(part, target)
            self._commit_total(total)
            reservation_active = False
            return DownloadResult(
                path=target,
                sha256=actual_hash,
                bytes_downloaded=total,
                content_type=response.headers.get("content-type"),
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
        except DownloadLimitError:
            part.unlink(missing_ok=True)
            raise
        except GeoDownloadError:
            part.unlink(missing_ok=True)
            raise
        except (httpx.TimeoutException, TimeoutError) as error:
            part.unlink(missing_ok=True)
            raise GeoDownloadError("DOWNLOAD_TIMEOUT") from error
        except OSError as error:
            part.unlink(missing_ok=True)
            raise GeoDownloadError("DOWNLOAD_WRITE_FAILED") from error
        finally:
            part.unlink(missing_ok=True)
            if reservation_active:
                self._release_reservation()

    def _reserve_total(self) -> None:
        with self._reservation_lock:
            if (
                self._downloaded_total
                + self._reserved_total
                + self._max_file_bytes
                > self._max_total_bytes
            ):
                raise DownloadLimitError()
            self._reserved_total += self._max_file_bytes

    def _commit_total(self, actual: int) -> None:
        with self._reservation_lock:
            self._reserved_total -= self._max_file_bytes
            self._downloaded_total += actual

    def _release_reservation(self) -> None:
        with self._reservation_lock:
            self._reserved_total = max(0, self._reserved_total - self._max_file_bytes)

    def _request_with_retries(
        self,
        url: str,
        deadline: float,
        cancel_event: Event | None,
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            self._check_cancel(cancel_event)
            if self._clock() > deadline:
                raise GeoDownloadError("DOWNLOAD_TIMEOUT")
            try:
                response = self._transport.get(url, timeout=self._connect_timeout)
            except GeoTransportError as error:
                if (
                    error.code
                    in {"DOWNLOAD_DNS_FAILED", "DOWNLOAD_NETWORK_ERROR", "DOWNLOAD_TIMEOUT"}
                    and attempt < self._max_retries
                ):
                    self._retry_sleep(0.0, deadline)
                    continue
                raise GeoDownloadError(error.code) from error
            except (httpx.TimeoutException, httpx.TransportError, TimeoutError) as error:
                if attempt < self._max_retries:
                    self._retry_sleep(0.0, deadline)
                    continue
                error_code = (
                    "DOWNLOAD_TIMEOUT"
                    if isinstance(error, (httpx.TimeoutException, TimeoutError))
                    else "DOWNLOAD_NETWORK_ERROR"
                )
                raise GeoDownloadError(error_code) from error
            if response.status_code in {429, 502, 503, 504}:
                retryable = attempt < self._max_retries
                retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                response.close()
                if retryable:
                    self._retry_sleep(retry_after, deadline)
                    continue
                error_code = (
                    "GEO_RATE_LIMITED"
                    if response.status_code == 429
                    else "DOWNLOAD_HTTP_ERROR"
                )
                raise GeoDownloadError(error_code)
            if response.status_code == 404:
                response.close()
                raise GeoDownloadError("DOWNLOAD_NOT_FOUND")
            if response.status_code >= 400:
                response.close()
                raise GeoDownloadError("DOWNLOAD_HTTP_ERROR")
            return response
        raise GeoDownloadError("DOWNLOAD_TIMEOUT")

    def _retry_sleep(self, requested: float, deadline: float) -> None:
        delay = min(max(0.0, requested), 60.0)
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise GeoDownloadError("DOWNLOAD_TIMEOUT")
        self._sleeper(min(delay, remaining))

    def _check_content_length(self, response: httpx.Response) -> None:
        raw_length = response.headers.get("content-length")
        if raw_length is None:
            return
        try:
            length = int(raw_length)
        except ValueError as error:
            response.close()
            raise GeoDownloadError("DOWNLOAD_INVALID_CONTENT_LENGTH") from error
        if length < 0 or length > self._max_file_bytes:
            response.close()
            raise DownloadLimitError()

    @staticmethod
    def _check_cancel(cancel_event: Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise GeoDownloadError("DOWNLOAD_CANCELLED")


def _retry_after_seconds(value: str | None) -> float:
    if value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 0.0


def download_file(
    transport: DownloadTransport | GeoTransport,
    url: str,
    destination: Path,
    **kwargs: object,
) -> DownloadResult:
    """Functional convenience wrapper around :class:`GeoDownloader`."""

    return GeoDownloader(transport).download(url, destination, **kwargs)  # type: ignore[arg-type]
