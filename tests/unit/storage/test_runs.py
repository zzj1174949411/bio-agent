from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from pydantic import JsonValue

from bioagent.storage.runs import RunRepository


@pytest.mark.parametrize("reader", ["read", "list_entries"])
def test_repository_does_not_replace_index_while_reader_is_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
) -> None:
    repository = RunRepository(tmp_path / "runs")
    run_id = str(uuid4())
    repository.write(run_id, _state(run_id, "QUEUED"))
    reading = Event()
    release_reader = Event()
    replacing = Event()
    writing = Event()
    original_read = Path.read_text
    original_replace = Path.replace

    def held_read(path: Path, *args, **kwargs):
        if path.name == "run.json":
            reading.set()
            assert release_reader.wait(5)
        return original_read(path, *args, **kwargs)

    def checked_replace(path: Path, target: Path):
        replacing.set()
        if not release_reader.is_set():
            raise PermissionError("simulated Windows reader sharing violation")
        return original_replace(path, target)

    def write_running():
        writing.set()
        return repository.write(run_id, _state(run_id, "RUNNING"))

    monkeypatch.setattr(Path, "read_text", held_read)
    monkeypatch.setattr(Path, "replace", checked_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        read_future = (
            pool.submit(repository.read, run_id)
            if reader == "read"
            else pool.submit(repository.list_entries)
        )
        try:
            assert reading.wait(5)
            write_future = pool.submit(write_running)
            assert writing.wait(5)
            assert not replacing.wait(0.2), "replacement overlapped an open index reader"
        finally:
            release_reader.set()
        read_future.result(timeout=5)
        write_future.result(timeout=5)
    assert repository.read(run_id)["status"] == "RUNNING"


def _state(run_id: str, status: str) -> dict[str, JsonValue]:
    return {
        "run_id": run_id,
        "dataset_id": str(uuid4()),
        "status": status,
    }


def test_list_entries_returns_empty_collections_for_missing_root(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path / "runs")

    assert repository.list_entries() == ((), ())


def test_list_entries_orders_valid_runs_and_isolates_corrupt_index(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    repository = RunRepository(runs_dir)
    older = str(uuid4())
    newer = str(uuid4())
    corrupt = str(uuid4())
    repository.write(older, _state(older, "FAILED"))
    repository.write(newer, _state(newer, "RUNNING"))
    os.utime(runs_dir / older / "run.json", (1, 1))
    os.utime(runs_dir / newer / "run.json", (2, 2))
    corrupt_dir = runs_dir / corrupt
    corrupt_dir.mkdir()
    (corrupt_dir / "run.json").write_text("not-json", encoding="utf-8")

    entries, issues = repository.list_entries()

    assert [entry.run_id for entry in entries] == [newer, older]
    assert [entry.state["status"] for entry in entries] == ["RUNNING", "FAILED"]
    assert all(entry.updated_at.tzinfo is not None for entry in entries)
    assert [(issue.run_id, issue.code) for issue in issues] == [(corrupt, "RUN_INDEX_INVALID")]


def test_list_entries_ignores_non_uuid_directories(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    repository = RunRepository(runs_dir)
    valid = str(uuid4())
    repository.write(valid, _state(valid, "CANCELLED"))
    invalid_dir = runs_dir / "not-a-run"
    invalid_dir.mkdir()
    (invalid_dir / "run.json").write_text("not-json", encoding="utf-8")

    entries, issues = repository.list_entries()

    assert [entry.run_id for entry in entries] == [valid]
    assert issues == ()


def test_list_entries_rejects_run_directory_resolving_outside_root(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    repository = RunRepository(runs_dir)
    run_id = str(uuid4())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.json").write_text(
        '{"run_id":"' + run_id + '","status":"FAILED"}',
        encoding="utf-8",
    )
    try:
        (runs_dir / run_id).symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")

    entries, issues = repository.list_entries()

    assert entries == ()
    assert [(issue.run_id, issue.code) for issue in issues] == [(run_id, "RUN_INDEX_INVALID")]
