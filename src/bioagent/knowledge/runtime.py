"""Cheap optional readiness and explicit, hash-verified offline model bundles."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from bioagent.knowledge.catalog import OCR_FILES, SOURCES, model_catalog
from bioagent.knowledge.store import KnowledgeError, file_hash

PARSER_VERSION = "2.58.0"
PREPARE_COMMAND = (
    "uv sync --extra rag --dev; uv run --extra rag python -m bioagent.knowledge.prepare "
    "--models-dir data/knowledge-models"
)


def bundle_path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or ":" in relative
        or parts.is_absolute()
        or (any(part in {".", ".."} for part in relative.split("/")))
    ):
        raise KnowledgeError("KNOWLEDGE_MODELS_INVALID")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise KnowledgeError("KNOWLEDGE_MODELS_INVALID")
    return path


def load_bundle(root: Path, *, verify: bool = True) -> tuple[dict[str, Any], str]:
    try:
        manifest_path = root / "bundle.json"
        if not manifest_path.is_file():
            raise KnowledgeError("KNOWLEDGE_MODELS_MISSING")
        raw = manifest_path.read_bytes()
        bundle = json.loads(raw)
        catalog = model_catalog()
        expected_files = {item["path"]: item["sha256"] for item in catalog}
        sizes = {item["path"]: item["bytes"] for item in catalog}
        if bundle["schema_version"] != "docling-bundle.v1" or (
            bundle["parser_version"] != PARSER_VERSION
            or bundle["files"] != expected_files
            or bundle["ocr"] != OCR_FILES
            or bundle["sources"] != SOURCES
        ):
            raise ValueError
        for relative, expected in bundle["files"].items():
            path = bundle_path(root, relative)
            if not path.is_file():
                raise KnowledgeError("KNOWLEDGE_MODELS_MISSING")
            if path.stat().st_size != sizes[relative]:
                raise KnowledgeError("KNOWLEDGE_MODELS_INVALID")
            if verify and file_hash(path) != expected:
                raise KnowledgeError("KNOWLEDGE_MODELS_INVALID")
        for key in ("det_model_path", "cls_model_path", "rec_model_path", "rec_keys_path"):
            if bundle["ocr"][key] not in bundle["files"]:
                raise ValueError
        return bundle, sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, KnowledgeError):
            raise
        raise KnowledgeError("KNOWLEDGE_MODELS_INVALID") from error


def readiness(models: Path, *, verify: bool = False) -> dict[str, Any]:
    try:
        if importlib.util.find_spec("docling") is None:
            raise KnowledgeError("KNOWLEDGE_DEPENDENCY_MISSING")
        if importlib.metadata.version("docling") != PARSER_VERSION:
            raise KnowledgeError("KNOWLEDGE_DEPENDENCY_VERSION")
        load_bundle(models, verify=verify)
        return {
            "ready": True,
            "code": "OK",
            "parser_version": PARSER_VERSION,
            "verification": "full_sha256" if verify else "presence_only",
        }
    except (KnowledgeError, importlib.metadata.PackageNotFoundError) as error:
        return {
            "ready": False,
            "code": getattr(error, "code", "KNOWLEDGE_DEPENDENCY_MISSING"),
            "prepare_command": PREPARE_COMMAND,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, required=True)
    options = parser.parse_args()
    result = readiness(options.models_dir, verify=True)
    print(json.dumps(result))
    raise SystemExit(0 if result["ready"] else 1)
