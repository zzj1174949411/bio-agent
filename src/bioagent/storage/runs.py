from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal, cast
from uuid import uuid4

from pydantic import JsonValue

from bioagent.domain.runs import RunStatus
from bioagent.workflow.state import ensure_json_safe, validate_run_id


@dataclass(frozen=True)
class RunIndexEntry:
    run_id: str
    state: dict[str, JsonValue]
    updated_at: datetime


@dataclass(frozen=True)
class RunIndexIssue:
    run_id: str
    code: Literal["RUN_INDEX_INVALID"] = "RUN_INDEX_INVALID"


class RunRepository:
    """Atomically persist the small API-facing run index outside checkpoints."""

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir.resolve()
        # Windows cannot atomically replace a file held open by an index reader.
        # All API and graph access shares this process-local repository instance.
        self._lock = RLock()

    def write(self, run_id: str, state: dict[str, JsonValue]) -> Path:
        with self._lock:
            return self._write(run_id, state)

    def _write(self, run_id: str, state: dict[str, JsonValue]) -> Path:
        run_dir = self._run_dir(run_id)
        self._validate_state(run_id, state)
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / "run.json"
        temporary = run_dir / f".run-{uuid4().hex}.tmp"
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def read(self, run_id: str) -> dict[str, JsonValue]:
        with self._lock:
            return self._read(run_id)

    def _read(self, run_id: str) -> dict[str, JsonValue]:
        target = self._run_dir(run_id) / "run.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("run index must contain a JSON object")
        state = cast(dict[str, JsonValue], payload)
        self._validate_state(run_id, state)
        return state

    def exists(self, run_id: str) -> bool:
        with self._lock:
            return (self._run_dir(run_id) / "run.json").is_file()

    def list_entries(
        self,
    ) -> tuple[tuple[RunIndexEntry, ...], tuple[RunIndexIssue, ...]]:
        with self._lock:
            return self._list_entries()

    def _list_entries(
        self,
    ) -> tuple[tuple[RunIndexEntry, ...], tuple[RunIndexIssue, ...]]:
        if not self._runs_dir.exists():
            return (), ()
        entries: list[RunIndexEntry] = []
        issues: list[RunIndexIssue] = []
        for candidate in self._runs_dir.iterdir():
            try:
                run_id = validate_run_id(candidate.name)
            except ValueError:
                continue
            try:
                state = self.read(run_id)
                updated_at = datetime.fromtimestamp(
                    (self._run_dir(run_id) / "run.json").stat().st_mtime,
                    tz=UTC,
                )
            except (OSError, TypeError, ValueError):
                issues.append(RunIndexIssue(run_id=run_id))
                continue
            entries.append(RunIndexEntry(run_id=run_id, state=state, updated_at=updated_at))
        entries.sort(key=lambda item: (-item.updated_at.timestamp(), item.run_id))
        issues.sort(key=lambda item: item.run_id)
        return tuple(entries), tuple(issues)

    def _run_dir(self, run_id: str) -> Path:
        validate_run_id(run_id)
        run_dir = (self._runs_dir / run_id).resolve()
        if self._runs_dir not in run_dir.parents:
            raise ValueError("invalid run path")
        return run_dir

    @staticmethod
    def _validate_state(run_id: str, state: dict[str, JsonValue]) -> None:
        ensure_json_safe(state)
        if state.get("run_id") != run_id:
            raise ValueError("run index run_id does not match target run")
        try:
            RunStatus(str(state.get("status")))
        except ValueError as error:
            raise ValueError("run index has invalid status") from error
