import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from bioagent.artifacts.manager import ArtifactManager

_UNSAFE_WINDOWS_ARTIFACT_IDS = (
    "results/CON",
    "results/con.txt",
    "results/NUL.tar.gz",
    "results/COM1.csv",
    "results/LPT9",
    "results/COM¹.txt",
    "results/LPT³.log",
    "results/table.csv:secret",
    "results/bad<name.csv",
    "results/bad>name.csv",
    'results/bad"name.csv',
    "results/bad|name.csv",
    "results/bad?name.csv",
    "results/bad*name.csv",
    "results/bad\x00name.csv",
    "results/bad\x01name.csv",
    "results/bad\x1fname.csv",
    "results/table.csv ",
    "results/table.csv.",
    "results /table.csv",
    "results./table.csv",
)


def test_create_run_uses_uuid4_and_expected_directories(tmp_path: Path) -> None:
    manager = ArtifactManager(tmp_path)

    run_id = manager.create_run()

    assert UUID(run_id).version == 4
    run_directory = tmp_path / run_id
    assert run_directory.is_dir()
    assert {
        path.name for path in run_directory.iterdir() if path.is_dir()
    } == {"input", "plans", "attempts", "report"}


@pytest.mark.parametrize(
    "artifact_id",
    [
        "../../secret.txt",
        "results/../secret.txt",
        "/absolute.txt",
        "C:/absolute.txt",
        r"C:\absolute.txt",
    ],
)
def test_artifact_id_cannot_escape_run_directory(
    tmp_path: Path,
    artifact_id: str,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()

    with pytest.raises(ValueError, match="invalid artifact id"):
        manager.resolve(run_id, artifact_id)


@pytest.mark.parametrize("artifact_id", _UNSAFE_WINDOWS_ARTIFACT_IDS)
def test_artifact_id_rejects_unsafe_windows_path_components(
    tmp_path: Path,
    artifact_id: str,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()

    with pytest.raises(ValueError, match="invalid artifact id"):
        manager.resolve(run_id, artifact_id)


@pytest.mark.parametrize(
    "artifact_id",
    [
        "results/.hidden",
        "results/COM10.csv",
        "results/LPT0.csv",
        "figures/火山图.png",
    ],
)
def test_artifact_id_accepts_portable_relative_paths(
    tmp_path: Path,
    artifact_id: str,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()

    assert manager.resolve(run_id, artifact_id).is_relative_to(tmp_path / run_id)


def test_write_bytes_returns_relative_path_and_sha256(tmp_path: Path) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    content = b"gene,padj\nA,0.01\n"

    result = manager.write_bytes(run_id, "attempts/results/table.csv", content)

    assert result.relative_path == "attempts/results/table.csv"
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert manager.resolve(run_id, result.relative_path).read_bytes() == content


def test_write_json_is_deterministic_and_hashed_from_written_bytes(
    tmp_path: Path,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()

    result = manager.write_json(run_id, "plans/plan-v1.json", {"z": 1, "a": "AD"})

    written = manager.resolve(run_id, result.relative_path).read_bytes()
    assert written == b'{"a":"AD","z":1}\n'
    assert json.loads(written) == {"a": "AD", "z": 1}
    assert result.sha256 == hashlib.sha256(written).hexdigest()


def test_resolve_rejects_invalid_run_id(tmp_path: Path) -> None:
    manager = ArtifactManager(tmp_path)

    with pytest.raises(ValueError, match="invalid run id"):
        manager.resolve("../../other-run", "results/table.csv")
