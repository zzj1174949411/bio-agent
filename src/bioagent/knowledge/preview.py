"""Bounded static PDF page rendering; no browser PDF plugins or document scripts."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Lock

import psutil

from bioagent.knowledge.service import KnowledgeService
from bioagent.knowledge.store import KnowledgeError

_RENDER_LOCK = Lock()
MAX_OUTPUT = 16 * 1024 * 1024


def render_page(source: Path, page: int) -> bytes:
    """Only the server passes a verified internal PDF and evidence page number."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
            "USERPROFILE",
            "HOME",
            "LANG",
            "LC_ALL",
        }
    }
    with _RENDER_LOCK, tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "bioagent.knowledge.preview", str(source), str(page)],
                shell=False,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise KnowledgeError("PREVIEW_UNAVAILABLE") from error
        start = time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic() - start > 15 or output.tell() > MAX_OUTPUT:
                    raise KnowledgeError("PREVIEW_UNAVAILABLE")
                try:
                    if psutil.Process(process.pid).memory_info().rss > 512 * 1024 * 1024:
                        raise KnowledgeError("PREVIEW_UNAVAILABLE")
                except psutil.NoSuchProcess:
                    pass
                time.sleep(0.05)
            if process.returncode != 0:
                raise KnowledgeError("PREVIEW_UNAVAILABLE")
            output.seek(0)
            data = output.read(MAX_OUTPUT + 1)
            if len(data) > MAX_OUTPUT or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise KnowledgeError("PREVIEW_UNAVAILABLE")
            return data
        finally:
            if process.poll() is None:
                KnowledgeService._kill(process)
            process.wait(timeout=5)


def _main() -> None:
    # Same explicit no-network boundary as ingestion; no Key/PYTHONPATH is inherited.
    import socket

    def blocked(*_: object, **__: object) -> None:
        raise RuntimeError("NETWORK_DISABLED")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign, assignment]
    socket.create_connection = blocked  # type: ignore[assignment]
    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    page_number = int(sys.argv[2])
    if not 1 <= page_number <= 200:
        raise ValueError("INVALID_PAGE")
    document = pdfium.PdfDocument(sys.argv[1])
    try:
        page = document[page_number - 1]
        width, height = page.get_size()
        if not 0 < max(width, height) < 100000:
            raise ValueError("INVALID_PAGE")
        bitmap = page.render(scale=min(2, 2000 / max(width, height)))
        image = bitmap.to_pil()
        image.save(sys.stdout.buffer, format="PNG")
        image.close()
        bitmap.close()
        page.close()
    finally:
        document.close()


if __name__ == "__main__":
    try:
        _main()
    except Exception:
        sys.exit(1)
