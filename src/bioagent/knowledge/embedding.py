"""Pinned offline E5 embeddings. Importing the module loads no optional package."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
from pathlib import Path
from typing import Protocol

from bioagent.knowledge.retrieval_models import RetrievalReadiness
from bioagent.knowledge.runtime import bundle_path
from bioagent.knowledge.store import KnowledgeError, file_hash

CATALOG = json.loads(Path(__file__).with_name("embedding_catalog.json").read_bytes())
# Algorithm identity changes require rebuilding even with identical model weights.
IDENTITY = f"{CATALOG['model_id']}@{CATALOG['revision']}:mean-l2-window480-v1"
PREPARE = (
    "uv sync --extra rag --dev; uv run --extra rag python -m "
    "bioagent.knowledge.prepare_embedding --models-dir data/embedding-models"
)


class Embedding(Protocol):
    identity: str
    dimension: int

    def encode(self, texts: list[str], *, query: bool = False) -> list[list[float]]: ...


def readiness(models: Path) -> RetrievalReadiness:
    code = "OK"
    try:
        for package, expected in {
            "transformers": "4.57.6",
            "torch": "2.14.1",
            "qdrant-client": "1.15.1",
        }.items():
            if importlib.metadata.version(package) != expected:
                raise KnowledgeError("RAG_DEPENDENCY_VERSION")
        for item in CATALOG["files"]:
            path = bundle_path(models, item["path"])
            if not path.is_file():
                raise KnowledgeError("RAG_MODELS_MISSING")
            if path.stat().st_size != item["bytes"] or file_hash(path) != item["sha256"]:
                raise KnowledgeError("RAG_MODELS_INVALID")
    except importlib.metadata.PackageNotFoundError:
        code = "RAG_DEPENDENCY_MISSING"
    except (OSError, KnowledgeError) as error:
        code = error.code if isinstance(error, KnowledgeError) else "RAG_MODELS_INVALID"
    return RetrievalReadiness(
        ready=code == "OK",
        code=code,
        model_id=CATALOG["model_id"],
        revision=CATALOG["revision"],
        dimension=CATALOG["dimension"],
        prepare_command=PREPARE if code != "OK" else None,
    )


class LocalE5:
    identity = IDENTITY
    dimension = 384

    def __init__(self, models: Path) -> None:
        result = readiness(models)
        if not result.ready:
            raise KnowledgeError(result.code)
        transformers = importlib.import_module("transformers")
        self.torch = importlib.import_module("torch")
        self.torch.set_num_threads(2)
        # Static allowlisted files, no pickle or remote model code, no Hub ID.
        self.tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(models.resolve()), local_files_only=True, trust_remote_code=False, use_fast=True
        )
        self.model = (
            transformers.AutoModel.from_pretrained(
                str(models.resolve()),
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
            )
            .to("cpu")
            .eval()
        )

    def encode(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        torch = self.torch
        output = []
        for text in texts:
            prefix = "query: " if query else "passage: "
            prefix_tokens = self.tokenizer.encode(prefix, add_special_tokens=False)
            tokens = self.tokenizer.encode(text, add_special_tokens=False)
            windows = [tokens[i : i + 480] for i in range(0, len(tokens), 480)] or [[]]
            pooled = []
            for window in windows:
                ids = self.tokenizer.build_inputs_with_special_tokens(prefix_tokens + window)
                encoded = {
                    "input_ids": torch.tensor([ids]),
                    "attention_mask": torch.ones((1, len(ids)), dtype=torch.long),
                }
                with torch.inference_mode():
                    hidden = self.model(**encoded).last_hidden_state
                    mask = encoded["attention_mask"].unsqueeze(-1).bool()
                    vector = hidden.masked_fill(~mask, 0.0).sum(dim=1) / mask.sum(dim=1)
                    pooled.append(torch.nn.functional.normalize(vector, p=2, dim=1))
            combined = torch.nn.functional.normalize(torch.stack(pooled).mean(dim=0), p=2, dim=1)
            output.append(combined[0].tolist())
        return output
