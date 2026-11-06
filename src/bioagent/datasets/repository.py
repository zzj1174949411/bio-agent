import json
import os
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DatasetHashes:
    counts_sha256: str
    metadata_sha256: str


class DatasetIntegrityError(ValueError):
    """Raised when stored dataset bytes no longer match their recorded hashes."""


class DatasetRepository:
    _ALLOWED_SUFFIXES = {".csv", ".tsv"}
    _METADATA_FILE = "dataset.json"

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        counts_bytes: bytes,
        metadata_bytes: bytes,
        counts_suffix: str,
        metadata_suffix: str,
    ) -> str:
        if counts_suffix not in self._ALLOWED_SUFFIXES:
            raise ValueError("unsupported counts suffix")
        if metadata_suffix not in self._ALLOWED_SUFFIXES:
            raise ValueError("unsupported metadata suffix")

        dataset_id = str(uuid4())
        dataset_dir = self._resolve_dataset_dir(dataset_id)
        dataset_dir.mkdir()
        try:
            counts_path = dataset_dir / f"counts{counts_suffix}"
            metadata_path = dataset_dir / f"metadata{metadata_suffix}"
            self._atomic_write_bytes(counts_path, counts_bytes)
            self._atomic_write_bytes(metadata_path, metadata_bytes)

            record = {
                "counts_suffix": counts_suffix,
                "metadata_suffix": metadata_suffix,
                "counts_sha256": self._file_sha256(counts_path),
                "metadata_sha256": self._file_sha256(metadata_path),
            }
            self._atomic_write_text(
                dataset_dir / self._METADATA_FILE,
                json.dumps(record, sort_keys=True, separators=(",", ":")),
            )
        except Exception:
            shutil.rmtree(dataset_dir, ignore_errors=True)
            raise
        return dataset_id

    def paths(self, dataset_id: str) -> tuple[Path, Path]:
        dataset_dir, record = self._record(dataset_id)
        return self._verified_paths(dataset_dir, record)

    def hashes(self, dataset_id: str) -> DatasetHashes:
        dataset_dir, record = self._record(dataset_id)
        self._verified_paths(dataset_dir, record)
        return DatasetHashes(
            counts_sha256=record["counts_sha256"],
            metadata_sha256=record["metadata_sha256"],
        )

    def remove(self, dataset_id: str) -> None:
        """Remove a dataset created by a failed multi-store import transaction."""
        try:
            parsed_id = UUID(dataset_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("invalid dataset id") from error
        if parsed_id.version != 4:
            raise ValueError("invalid dataset id")
        dataset_dir = self._root / str(parsed_id)
        self._ensure_within_root(dataset_dir.resolve())
        if dataset_dir.is_symlink() or not dataset_dir.is_dir():
            return
        shutil.rmtree(dataset_dir)

    def _verified_paths(
        self,
        dataset_dir: Path,
        record: dict[str, str],
    ) -> tuple[Path, Path]:
        counts_suffix = record["counts_suffix"]
        metadata_suffix = record["metadata_suffix"]
        if counts_suffix not in self._ALLOWED_SUFFIXES:
            raise ValueError("invalid stored counts suffix")
        if metadata_suffix not in self._ALLOWED_SUFFIXES:
            raise ValueError("invalid stored metadata suffix")

        counts_path = (dataset_dir / f"counts{counts_suffix}").resolve()
        metadata_path = (dataset_dir / f"metadata{metadata_suffix}").resolve()
        self._ensure_within_root(counts_path)
        self._ensure_within_root(metadata_path)
        if not counts_path.is_file() or not metadata_path.is_file():
            raise FileNotFoundError("dataset files not found")

        if self._file_sha256(counts_path) != record["counts_sha256"]:
            raise DatasetIntegrityError("counts SHA-256 mismatch")
        if self._file_sha256(metadata_path) != record["metadata_sha256"]:
            raise DatasetIntegrityError("metadata SHA-256 mismatch")
        return counts_path, metadata_path

    def _record(self, dataset_id: str) -> tuple[Path, dict[str, str]]:
        dataset_dir = self._resolve_dataset_dir(dataset_id)
        if not dataset_dir.is_dir():
            raise FileNotFoundError("dataset not found")

        metadata_path = (dataset_dir / self._METADATA_FILE).resolve()
        self._ensure_within_root(metadata_path)
        if not metadata_path.is_file():
            raise FileNotFoundError("dataset metadata not found")

        payload: object = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid dataset metadata")

        required = {
            "counts_suffix",
            "metadata_suffix",
            "counts_sha256",
            "metadata_sha256",
        }
        record: dict[str, str] = {}
        for key in required:
            value = payload.get(key)
            if not isinstance(value, str):
                raise ValueError("invalid dataset metadata")
            record[key] = value
        return dataset_dir, record

    def _resolve_dataset_dir(self, dataset_id: str) -> Path:
        try:
            parsed_id = UUID(dataset_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("invalid dataset id") from error
        if parsed_id.version != 4:
            raise ValueError("invalid dataset id")

        dataset_dir = (self._root / str(parsed_id)).resolve()
        self._ensure_within_root(dataset_dir)
        return dataset_dir

    def _ensure_within_root(self, path: Path) -> None:
        if self._root not in path.parents:
            raise ValueError("invalid dataset path")

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(content)
        os.replace(temporary, path)

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
