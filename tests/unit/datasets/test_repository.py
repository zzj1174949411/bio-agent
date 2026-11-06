from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from bioagent.datasets.repository import DatasetIntegrityError, DatasetRepository

COUNTS = b"feature_id,S1\nG1,1\n"
METADATA = b"sample_id\tcondition\nS1\tA\n"


def test_create_uses_uuid4_directory_and_fixed_file_names(tmp_path: Path) -> None:
    repository = DatasetRepository(tmp_path)

    dataset_id = repository.create(COUNTS, METADATA, ".csv", ".tsv")
    counts_path, metadata_path = repository.paths(dataset_id)

    assert UUID(dataset_id).version == 4
    assert counts_path == tmp_path.resolve() / dataset_id / "counts.csv"
    assert metadata_path == tmp_path.resolve() / dataset_id / "metadata.tsv"
    assert counts_path.read_bytes() == COUNTS
    assert metadata_path.read_bytes() == METADATA


def test_create_persists_sha256_for_provenance(tmp_path: Path) -> None:
    dataset_id = DatasetRepository(tmp_path).create(COUNTS, METADATA, ".csv", ".tsv")

    hashes = DatasetRepository(tmp_path).hashes(dataset_id)

    assert hashes.counts_sha256 == sha256(COUNTS).hexdigest()
    assert hashes.metadata_sha256 == sha256(METADATA).hexdigest()
    with pytest.raises(FrozenInstanceError):
        hashes.counts_sha256 = "tampered"


@pytest.mark.parametrize(
    ("file_name", "label"),
    [("counts.csv", "counts"), ("metadata.tsv", "metadata")],
)
@pytest.mark.parametrize("accessor", ["paths", "hashes"])
def test_repository_rejects_tampered_dataset_files(
    tmp_path: Path,
    file_name: str,
    label: str,
    accessor: str,
) -> None:
    repository = DatasetRepository(tmp_path)
    dataset_id = repository.create(COUNTS, METADATA, ".csv", ".tsv")
    (tmp_path / dataset_id / file_name).write_bytes(b"tampered")

    with pytest.raises(
        DatasetIntegrityError,
        match=rf"{label} SHA-256 mismatch",
    ):
        getattr(repository, accessor)(dataset_id)


@pytest.mark.parametrize(
    ("counts_suffix", "metadata_suffix", "message"),
    [
        (".txt", ".csv", "unsupported counts suffix"),
        (".csv", ".xlsx", "unsupported metadata suffix"),
    ],
)
def test_create_rejects_unsupported_suffixes(
    tmp_path: Path,
    counts_suffix: str,
    metadata_suffix: str,
    message: str,
) -> None:
    repository = DatasetRepository(tmp_path)

    with pytest.raises(ValueError, match=message):
        repository.create(COUNTS, METADATA, counts_suffix, metadata_suffix)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("dataset_id", ["not-a-uuid", "../../outside"])
def test_paths_rejects_invalid_dataset_id(tmp_path: Path, dataset_id: str) -> None:
    repository = DatasetRepository(tmp_path)

    with pytest.raises(ValueError, match="invalid dataset id"):
        repository.paths(dataset_id)


def test_paths_reports_missing_dataset(tmp_path: Path) -> None:
    repository = DatasetRepository(tmp_path)

    with pytest.raises(FileNotFoundError, match="dataset not found"):
        repository.paths("d8d2b636-c64c-4b5c-8ee6-3581668b9092")
