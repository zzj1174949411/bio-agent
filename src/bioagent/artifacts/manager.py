import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import JsonValue

from bioagent.artifacts.manifest import ArtifactRecord, RunManifest, write_manifest_atomic
from bioagent.artifacts.paths import validate_artifact_relative_path


class ArtifactManager:
    _RUN_DIRECTORIES = ("input", "plans", "attempts", "report")

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def create_run(self) -> str:
        run_id = str(uuid4())
        run_directory = self._resolve_run_directory(run_id)
        run_directory.mkdir()
        for directory in self._RUN_DIRECTORIES:
            (run_directory / directory).mkdir()
        return run_id

    def resolve(self, run_id: str, artifact_id: str) -> Path:
        run_directory = self._resolve_run_directory(run_id)
        if not run_directory.is_dir():
            raise FileNotFoundError("run not found")

        try:
            parts = validate_artifact_relative_path(artifact_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("invalid artifact id") from error

        resolved = run_directory.joinpath(*parts).resolve()
        if run_directory not in resolved.parents:
            raise ValueError("invalid artifact id")
        return resolved

    def write_bytes(self, run_id: str, artifact_id: str, content: bytes) -> ArtifactRecord:
        path = self.resolve(run_id, artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return ArtifactRecord(
            relative_path=artifact_id,
            sha256=sha256(content).hexdigest(),
        )

    def write_json(
        self,
        run_id: str,
        artifact_id: str,
        payload: JsonValue,
    ) -> ArtifactRecord:
        content = (
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode()
        return self.write_bytes(run_id, artifact_id, content)

    def write_manifest(
        self,
        run_id: str,
        manifest: RunManifest,
    ) -> ArtifactRecord:
        run_directory = self._resolve_run_directory(run_id)
        if str(manifest.run_id) != run_directory.name:
            raise ValueError("manifest run id does not match target run")

        path = self.resolve(run_id, "manifest.json")
        digest = write_manifest_atomic(path, manifest)
        return ArtifactRecord(relative_path="manifest.json", sha256=digest)

    def _resolve_run_directory(self, run_id: str) -> Path:
        try:
            parsed_id = UUID(run_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("invalid run id") from error
        if parsed_id.version != 4:
            raise ValueError("invalid run id")

        run_directory = (self._root / str(parsed_id)).resolve()
        if self._root not in run_directory.parents:
            raise ValueError("invalid run path")
        return run_directory
