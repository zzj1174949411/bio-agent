import gzip
import hashlib
from pathlib import Path
from threading import Event

import httpx
import pytest

from bioagent.geo.download import (
    DownloadLimitError,
    GeoDownloader,
    GeoDownloadError,
    checked_total,
    expand_gzip,
)


class FakeTransport:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.calls = 0

    def get(self, url: str, **_: object) -> httpx.Response:
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


def _response(
    content: bytes,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", "https://www.ncbi.nlm.nih.gov/example.tsv")
    return httpx.Response(status, content=content, headers=headers, request=request)


def test_gzip_limit_leaves_no_published_file(tmp_path: Path) -> None:
    source = tmp_path / "large.gz"
    target = tmp_path / "counts.tsv"
    source.write_bytes(gzip.compress(b"A" * 4096))

    with pytest.raises(DownloadLimitError, match="^DOWNLOAD_TOO_LARGE$"):
        expand_gzip(source, target, max_bytes=1024)

    assert not target.exists()
    assert source.exists()
    assert not list(tmp_path.glob("*.part"))


def test_gzip_does_not_overwrite_existing_evidence(tmp_path: Path) -> None:
    source = tmp_path / "counts.tsv.gz"
    target = tmp_path / "counts.tsv"
    source.write_bytes(gzip.compress(b"new"))
    target.write_bytes(b"old")

    with pytest.raises(GeoDownloadError, match="^DOWNLOAD_TARGET_EXISTS$"):
        expand_gzip(source, target, max_bytes=1024)

    assert target.read_bytes() == b"old"
    assert source.exists()


def test_corrupt_gzip_cleans_temp_and_keeps_source(tmp_path: Path) -> None:
    source = tmp_path / "broken.gz"
    target = tmp_path / "counts.tsv"
    source.write_bytes(b"not gzip")

    with pytest.raises(GeoDownloadError, match="^DOWNLOAD_INVALID_GZIP$"):
        expand_gzip(source, target, max_bytes=1024)

    assert source.read_bytes() == b"not gzip"
    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))


def test_checked_total_rejects_actual_stream_bytes() -> None:
    assert checked_total(4, b"abc", 8) == 7
    with pytest.raises(DownloadLimitError, match="^DOWNLOAD_TOO_LARGE$"):
        checked_total(4, b"abcde", 8)


def test_gzip_rejects_path_traversal_and_non_regular_source(tmp_path: Path) -> None:
    source = tmp_path / "counts.gz"
    source.write_bytes(gzip.compress(b"counts"))

    with pytest.raises(GeoDownloadError, match="^DOWNLOAD_PATH_REJECTED$"):
        expand_gzip(source, tmp_path / ".." / "outside.tsv", max_bytes=1024)

    with pytest.raises(GeoDownloadError, match="^DOWNLOAD_SOURCE_INVALID$"):
        expand_gzip(tmp_path, tmp_path / "counts.tsv", max_bytes=1024)


def test_download_enforces_instance_total_byte_budget(tmp_path: Path) -> None:
    transport = FakeTransport([_response(b"1234"), _response(b"5678")])
    downloader = GeoDownloader(
        transport,
        max_file_bytes=4,
        max_total_bytes=6,
        disk_reserve_bytes=0,
    )

    downloader.download("https://www.ncbi.nlm.nih.gov/one.tsv", tmp_path / "one.tsv")
    with pytest.raises(DownloadLimitError, match="^DOWNLOAD_TOO_LARGE$"):
        downloader.download("https://www.ncbi.nlm.nih.gov/two.tsv", tmp_path / "two.tsv")

    assert transport.calls == 1
    assert (tmp_path / "one.tsv").read_bytes() == b"1234"
    assert not (tmp_path / "two.tsv").exists()


def test_download_rejects_content_length_before_writing(tmp_path: Path) -> None:
    transport = FakeTransport([_response(b"small", headers={"Content-Length": "100"})])
    downloader = GeoDownloader(
        transport,
        max_file_bytes=10,
        max_total_bytes=100,
        disk_reserve_bytes=0,
    )

    with pytest.raises(DownloadLimitError, match="^DOWNLOAD_TOO_LARGE$"):
        downloader.download("https://www.ncbi.nlm.nih.gov/counts.tsv", tmp_path / "counts.tsv")

    assert transport.calls == 1
    assert not list(tmp_path.iterdir())


def test_download_rejects_actual_stream_over_limit_and_cleans_part(tmp_path: Path) -> None:
    transport = FakeTransport([_response(b"0123456789")])
    downloader = GeoDownloader(
        transport,
        max_file_bytes=5,
        max_total_bytes=100,
        disk_reserve_bytes=0,
    )

    with pytest.raises(DownloadLimitError, match="^DOWNLOAD_TOO_LARGE$"):
        downloader.download("https://www.ncbi.nlm.nih.gov/counts.tsv", tmp_path / "counts.tsv")

    assert not (tmp_path / "counts.tsv").exists()
    assert not list(tmp_path.glob("*.part"))


def test_download_retries_transient_response_and_publishes_hash(tmp_path: Path) -> None:
    body = b"feature_id\tGSM1\nGENE1\t4\n"
    transport = FakeTransport(
        [
            _response(b"busy", status=503, headers={"Retry-After": "0"}),
            _response(body),
        ]
    )
    sleeps: list[float] = []
    downloader = GeoDownloader(
        transport,
        max_file_bytes=1024,
        max_total_bytes=2048,
        disk_reserve_bytes=0,
        sleeper=sleeps.append,
    )
    target = tmp_path / "counts.tsv"

    result = downloader.download("https://www.ncbi.nlm.nih.gov/counts.tsv", target)

    assert transport.calls == 2
    assert sleeps == [0.0]
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.bytes_downloaded == len(body)
    assert target.read_bytes() == body
    assert not list(tmp_path.glob("*.part"))


def test_download_hash_mismatch_never_publishes(tmp_path: Path) -> None:
    body = b"counts"
    transport = FakeTransport([_response(body)])
    downloader = GeoDownloader(transport, max_file_bytes=1024, disk_reserve_bytes=0)

    with pytest.raises(GeoDownloadError, match="^SOURCE_CHANGED$"):
        downloader.download(
            "https://www.ncbi.nlm.nih.gov/counts.tsv",
            tmp_path / "counts.tsv",
            expected_sha256="0" * 64,
        )

    assert not (tmp_path / "counts.tsv").exists()
    assert not list(tmp_path.glob("*.part"))


def test_download_cancellation_cleans_only_its_part(tmp_path: Path) -> None:
    event = Event()
    event.set()
    transport = FakeTransport([_response(b"counts")])
    downloader = GeoDownloader(transport, max_file_bytes=1024, disk_reserve_bytes=0)

    with pytest.raises(GeoDownloadError, match="^DOWNLOAD_CANCELLED$"):
        downloader.download(
            "https://www.ncbi.nlm.nih.gov/counts.tsv",
            tmp_path / "counts.tsv",
            cancel_event=event,
        )

    assert not list(tmp_path.glob("*.part"))
