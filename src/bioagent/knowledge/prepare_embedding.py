"""Explicit fixed-source embedding weight download; never invoked by the API."""

import argparse
import json
from pathlib import Path

import httpx

from bioagent.knowledge.embedding import CATALOG, readiness
from bioagent.knowledge.prepare import _download
from bioagent.knowledge.runtime import bundle_path
from bioagent.knowledge.store import KnowledgeError


def prepare(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=15)) as client:
        for item in CATALOG["files"]:
            url = (
                f"https://huggingface.co/{CATALOG['model_id']}/resolve/"
                f"{CATALOG['revision']}/{item['path']}"
            )
            _download(client, url, bundle_path(root, item["path"]), item["bytes"], item["sha256"])
            print(f"Verified {item['path']} ({item['bytes']} bytes)", flush=True)
    result = readiness(root)
    print(result.model_dump_json(), flush=True)
    if not result.ready:
        raise KnowledgeError(result.code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, required=True)
    options = parser.parse_args()
    try:
        prepare(options.models_dir)
    except (httpx.HTTPError, OSError, KnowledgeError):
        print(json.dumps({"code": "EMBEDDING_PREPARATION_FAILED"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
