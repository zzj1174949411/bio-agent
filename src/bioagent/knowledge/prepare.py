"""Explicit, bounded download of the audited local parser model bundle."""

from __future__ import annotations

import argparse
import json
import time
from contextlib import suppress
from pathlib import Path

import httpx

from bioagent.knowledge.catalog import OCR_FILES, SOURCES, model_catalog
from bioagent.knowledge.runtime import PARSER_VERSION, bundle_path, load_bundle
from bioagent.knowledge.store import KnowledgeError, file_hash


def _download(client: httpx.Client, url: str, path: Path, size: int, digest: str) -> None:
    if path.is_file() and path.stat().st_size == size and file_hash(path) == digest:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    if partial.is_symlink():
        raise KnowledgeError("KNOWLEDGE_MODELS_INVALID")
    try:
        with partial.open("wb") as target:
            start = 0
            while start < size:
                end = min(start + 4 * 1024 * 1024, size) - 1
                for attempt in range(3):
                    try:
                        # A fresh canonical request per range avoids reusing an expired
                        # signed redirect. These URLs come only from the static catalog.
                        with client.stream(
                            "GET",
                            url,
                            params={
                                "download": "true",
                                "offset": str(start),
                                "attempt": str(attempt),
                                "stamp": str(time.time_ns()),
                            },
                            headers={
                                "Range": f"bytes={start}-{end}",
                                "Accept-Encoding": "identity",
                            },
                        ) as response:
                            response.raise_for_status()
                            if response.status_code == 206:
                                if response.headers.get("content-range") != (
                                    f"bytes {start}-{end}/{size}"
                                ):
                                    raise KnowledgeError("MODEL_DOWNLOAD_RANGE_INVALID")
                                expected = end - start + 1
                            elif response.status_code == 200 and start == 0:
                                expected = size
                            else:
                                raise KnowledgeError("MODEL_DOWNLOAD_RANGE_INVALID")
                            written = 0
                            target.seek(start)
                            for block in response.iter_bytes(256 * 1024):
                                written += len(block)
                                if written > expected:
                                    raise KnowledgeError("MODEL_DOWNLOAD_SIZE_INVALID")
                                target.write(block)
                            if written != expected:
                                raise KnowledgeError("MODEL_DOWNLOAD_SIZE_INVALID")
                            start += written
                            break
                    except (httpx.HTTPError, KnowledgeError):
                        if attempt == 2:
                            raise
            target.truncate(size)
        if partial.stat().st_size != size or file_hash(partial) != digest:
            raise KnowledgeError("MODEL_DOWNLOAD_HASH_INVALID")
        partial.replace(path)
    finally:
        with suppress(OSError):
            partial.unlink(missing_ok=True)


def prepare(root: Path) -> None:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    catalog = model_catalog()
    with httpx.Client(
        # Explicit preparation supports the user's normal HTTPS proxy/cert settings.
        # Runtime parser workers inherit neither proxy credentials nor network access.
        follow_redirects=True,
        timeout=httpx.Timeout(30, connect=15),
        trust_env=True,
    ) as client:
        for item in catalog:
            _download(
                client, item["url"], bundle_path(root, item["path"]), item["bytes"], item["sha256"]
            )
            print(f"Verified {item['path']} ({item['bytes']} bytes)")
    bundle = {
        "schema_version": "docling-bundle.v1",
        "parser_version": PARSER_VERSION,
        "files": {item["path"]: item["sha256"] for item in catalog},
        "ocr": OCR_FILES,
        "sources": SOURCES,
    }
    manifest = root / "bundle.json"
    temporary = bundle_path(root, "bundle.json.tmp")
    temporary.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest)
    load_bundle(root, verify=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, required=True)
    options = parser.parse_args()
    try:
        prepare(options.models_dir)
        print("Local parser model bundle is ready.")
        return 0
    except (OSError, httpx.HTTPError, KnowledgeError):
        print("Model preparation failed; no incomplete model bundle may be used. Retry prepare.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
