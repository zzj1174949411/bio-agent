from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import (
    AgentContext,
    ApprovalRecord,
    ArtifactRecord,
    AttemptRecord,
    RunManifest,
)
from bioagent.datasets.parser import load_dataset
from bioagent.datasets.repository import DatasetHashes, DatasetRepository
from bioagent.datasets.validator import DatasetValidation, validate_dataset
from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCIssue, QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.r_runner import RExecutionCancelledError, RRunnerError
from bioagent.tools.deseq2 import validate_deseq2_outputs, write_deseq2_parameters
from bioagent.tools.registry import ToolSpec

CancellationCheck = Callable[[], bool]


class _Runner(Protocol):
    def run(
        self,
        *,
        spec: ToolSpec,
        attempt_dir: Path,
        parameters: Path,
        cancelled: CancellationCheck | None = None,
    ) -> object: ...


class _Registry(Protocol):
    def get(self, name: str) -> ToolSpec: ...


@dataclass(frozen=True)
class ExecutionResult:
    attempt_id: str
    execution_key: str
    status: RunStatus
    qc: QCReport
    reused: bool

    def workflow_output(self) -> dict[str, JsonValue]:
        return {
            "attempt_id": self.attempt_id,
            "qc": cast(dict[str, JsonValue], self.qc.model_dump(mode="json")),
        }


def calculate_plan_hash(plan: AnalysisPlan) -> str:
    validated = AnalysisPlan.model_validate(plan.model_dump(mode="python", round_trip=True))
    payload = validated.model_dump(mode="json", exclude_none=True)
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def calculate_execution_key(
    *,
    run_id: str,
    plan_hash: str,
    input_hashes: Mapping[str, str],
) -> str:
    payload = {
        "run_id": run_id,
        "plan_hash": plan_hash,
        "input_hashes": dict(input_hashes),
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical_json.encode("utf-8")).hexdigest()


class ExecutionRejectedError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ExecutionController:
    def __init__(
        self,
        *,
        project_root: Path,
        r_runner: _Runner,
        dataset_repository: DatasetRepository,
        artifact_manager: ArtifactManager,
        tool_registry: _Registry,
        git_commit: str,
        software_versions: Mapping[str, str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._project_root = project_root.resolve()
        self._r_runner = r_runner
        self._dataset_repository = dataset_repository
        self._artifact_manager = artifact_manager
        self._tool_registry = tool_registry
        self._git_commit = git_commit
        self._software_versions = dict(software_versions)
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        state: Mapping[str, object],
        cancelled: CancellationCheck | None = None,
    ) -> ExecutionResult:
        self._require_execution_status(state)
        plan, revision, plan_hash, approval = self._approved_plan(state)
        agent_context = self._agent_context(state)
        run_id = self._run_id(state)
        if state.get("dataset_id") not in {None, plan.dataset_id}:
            raise ExecutionRejectedError("DATASET_ID_MISMATCH")

        spec = self._tool_registry.get(plan.tool)
        if plan.schema_version not in spec.plan_schema_versions:
            raise ExecutionRejectedError("PLAN_SCHEMA_UNSUPPORTED")

        counts_path, metadata_path = self._dataset_repository.paths(plan.dataset_id)
        dataset = load_dataset(counts_path, metadata_path)
        validation = validate_dataset(dataset, plan.comparison)
        if not validation.is_valid:
            raise ExecutionRejectedError("DATASET_VALIDATION_FAILED")
        dataset_hashes = self._dataset_repository.hashes(plan.dataset_id)
        input_hashes = {
            "counts": dataset_hashes.counts_sha256,
            "metadata": dataset_hashes.metadata_sha256,
        }
        execution_key = calculate_execution_key(
            run_id=run_id,
            plan_hash=plan_hash,
            input_hashes=input_hashes,
        )
        current_approval = self._approval_record(approval, revision, plan_hash)
        previous_manifest = self._load_manifest(run_id)
        self._bind_existing_run(
            previous_manifest,
            run_id,
            plan,
            input_hashes,
            agent_context,
        )
        source_records = self._source_records(run_id, agent_context, plan.dataset_id)
        if (
            previous_manifest is not None
            and previous_manifest.source_artifacts
            and tuple(source_records) != previous_manifest.source_artifacts
        ):
            raise ExecutionRejectedError("SOURCE_ARTIFACT_TAMPERED")
        recovered_attempts, recovered_artifacts = self._recover_orphan_attempts(
            run_id=run_id,
            spec=spec,
            previous=previous_manifest,
        )
        input_records, plan_record, snapshot_paths = self._write_run_inputs(
            run_id=run_id,
            plan=plan,
            revision=revision,
            counts_path=counts_path,
            metadata_path=metadata_path,
            expected_hashes=dataset_hashes,
        )
        reused = None
        if not recovered_attempts:
            reused = self._reuse_completed_attempt(
                run_id=run_id,
                plan=plan,
                revision=revision,
                plan_hash=plan_hash,
                input_hashes=input_hashes,
                validation=validation,
                spec=spec,
                approval=current_approval,
                previous=previous_manifest,
                run_records=(*input_records, plan_record),
                source_records=source_records,
                snapshot_paths=snapshot_paths,
                execution_key=execution_key,
                agent_context=agent_context,
            )
        if reused is not None:
            return reused

        return self._execute_new_attempt(
            run_id=run_id,
            plan=plan,
            revision=revision,
            plan_hash=plan_hash,
            input_hashes=input_hashes,
            validation=validation,
            spec=spec,
            approval=current_approval,
            previous=previous_manifest,
            recovered_attempts=recovered_attempts,
            recovered_artifacts=recovered_artifacts,
            run_records=(*input_records, plan_record),
            source_records=source_records,
            snapshot_paths=snapshot_paths,
            execution_key=execution_key,
            cancelled=cancelled,
            agent_context=agent_context,
        )

    def execution_key(self, state: Mapping[str, object]) -> str:
        """Return the stable key used by ``LocalJobRunner`` for in-flight dedupe."""

        self._require_execution_status(state)
        plan, _, plan_hash, _ = self._approved_plan(state)
        run_id = self._run_id(state)
        if state.get("dataset_id") not in {None, plan.dataset_id}:
            raise ExecutionRejectedError("DATASET_ID_MISMATCH")
        self._dataset_repository.paths(plan.dataset_id)
        dataset_hashes = self._dataset_repository.hashes(plan.dataset_id)
        return calculate_execution_key(
            run_id=run_id,
            plan_hash=plan_hash,
            input_hashes={
                "counts": dataset_hashes.counts_sha256,
                "metadata": dataset_hashes.metadata_sha256,
            },
        )

    def _approved_plan(
        self, state: Mapping[str, object]
    ) -> tuple[AnalysisPlan, int, str, Mapping[str, object]]:
        approval = state.get("approval")
        if (
            not isinstance(approval, Mapping)
            or approval.get("status") != "APPROVED"
            or approval.get("action") != "approve"
        ):
            raise ExecutionRejectedError("PLAN_NOT_APPROVED")
        revision = state.get("plan_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ExecutionRejectedError("PLAN_REVISION_INVALID")
        if approval.get("plan_revision") != revision:
            raise ExecutionRejectedError("PLAN_REVISION_MISMATCH")
        try:
            plan = AnalysisPlan.model_validate(state.get("plan"))
        except ValidationError as error:
            raise ExecutionRejectedError("PLAN_INVALID") from error
        plan_hash = calculate_plan_hash(plan)
        if approval.get("plan_hash") != plan_hash:
            raise ExecutionRejectedError("PLAN_HASH_MISMATCH")
        return plan, revision, plan_hash, approval

    @staticmethod
    def _require_execution_status(state: Mapping[str, object]) -> None:
        if state.get("status") not in {
            RunStatus.QUEUED.value,
            RunStatus.RUNNING.value,
        }:
            raise ExecutionRejectedError("RUN_STATUS_INVALID")

    def _run_id(self, state: Mapping[str, object]) -> str:
        value = state.get("run_id")
        if not isinstance(value, str):
            raise ExecutionRejectedError("RUN_ID_INVALID")
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise ExecutionRejectedError("RUN_ID_INVALID") from error
        if parsed.version != 4 or str(parsed) != value:
            raise ExecutionRejectedError("RUN_ID_INVALID")
        return value

    def _write_run_inputs(
        self,
        *,
        run_id: str,
        plan: AnalysisPlan,
        revision: int,
        counts_path: Path,
        metadata_path: Path,
        expected_hashes: DatasetHashes,
    ) -> tuple[tuple[ArtifactRecord, ArtifactRecord], ArtifactRecord, tuple[Path, Path]]:
        counts_bytes = counts_path.read_bytes()
        metadata_bytes = metadata_path.read_bytes()
        if sha256(counts_bytes).hexdigest() != expected_hashes.counts_sha256:
            raise ExecutionRejectedError("DATASET_HASH_CHANGED")
        if sha256(metadata_bytes).hexdigest() != expected_hashes.metadata_sha256:
            raise ExecutionRejectedError("DATASET_HASH_CHANGED")
        counts_artifact_id = f"input/counts{counts_path.suffix}"
        metadata_artifact_id = f"input/metadata{metadata_path.suffix}"
        counts_record = self._artifact_manager.write_bytes(run_id, counts_artifact_id, counts_bytes)
        metadata_record = self._artifact_manager.write_bytes(
            run_id, metadata_artifact_id, metadata_bytes
        )
        plan_record = self._artifact_manager.write_json(
            run_id,
            f"plans/plan-v{revision}.json",
            cast(JsonValue, plan.model_dump(mode="json")),
        )
        return (
            (counts_record, metadata_record),
            plan_record,
            (
                self._artifact_manager.resolve(run_id, counts_artifact_id),
                self._artifact_manager.resolve(run_id, metadata_artifact_id),
            ),
        )

    def _execute_new_attempt(
        self,
        *,
        run_id: str,
        plan: AnalysisPlan,
        revision: int,
        plan_hash: str,
        input_hashes: Mapping[str, str],
        validation: DatasetValidation,
        spec: ToolSpec,
        approval: ApprovalRecord,
        previous: RunManifest | None,
        recovered_attempts: Sequence[AttemptRecord],
        recovered_artifacts: Sequence[ArtifactRecord],
        run_records: Sequence[ArtifactRecord],
        source_records: Sequence[ArtifactRecord],
        snapshot_paths: tuple[Path, Path],
        execution_key: str,
        cancelled: CancellationCheck | None,
        agent_context: AgentContext | None,
    ) -> ExecutionResult:
        attempt_id = str(uuid4())
        started_at = self._now()
        attempt_dir = self._artifact_manager.resolve(run_id, f"attempts/{attempt_id}")
        attempt_dir.mkdir()
        running_attempt = AttemptRecord(
            attempt_id=UUID(attempt_id),
            started_at=started_at,
            status=RunStatus.RUNNING,
        )
        self._write_attempt(run_id, running_attempt)
        try:
            parameters = write_deseq2_parameters(
                plan=plan,
                project_root=self._project_root,
                counts_path=snapshot_paths[0],
                metadata_path=snapshot_paths[1],
                attempt_dir=attempt_dir,
            )
            self._r_runner.run(
                spec=spec,
                attempt_dir=attempt_dir,
                parameters=parameters,
                cancelled=cancelled,
            )
            qc = self._validate_outputs(plan, validation, spec, attempt_dir)
            status = RunStatus.FAILED if qc.status is QCStatus.FAIL else RunStatus.COMPLETED
        except Exception as error:
            status = (
                RunStatus.CANCELLED
                if isinstance(error, RExecutionCancelledError)
                else RunStatus.FAILED
            )
            qc = self._execution_failure_qc(error)
            terminal_attempt = AttemptRecord(
                attempt_id=UUID(attempt_id),
                started_at=started_at,
                ended_at=self._now(),
                status=status,
                qc=qc,
            )
            attempt_records = self._finish_attempt(run_id, terminal_attempt, spec)
            self._write_terminal_manifest(
                run_id=run_id,
                plan=plan,
                revision=revision,
                plan_hash=plan_hash,
                input_hashes=input_hashes,
                approval=approval,
                previous=previous,
                recovered_attempts=recovered_attempts,
                attempt=terminal_attempt,
                artifacts=(
                    *run_records,
                    *source_records,
                    *recovered_artifacts,
                    *attempt_records,
                ),
                source_records=source_records,
                agent_context=agent_context,
            )
            return ExecutionResult(
                attempt_id=attempt_id,
                execution_key=execution_key,
                status=status,
                qc=qc,
                reused=False,
            )

        terminal_attempt = AttemptRecord(
            attempt_id=UUID(attempt_id),
            started_at=started_at,
            ended_at=self._now(),
            status=status,
            qc=qc,
        )
        attempt_records = self._finish_attempt(run_id, terminal_attempt, spec)
        self._write_terminal_manifest(
            run_id=run_id,
            plan=plan,
            revision=revision,
            plan_hash=plan_hash,
            input_hashes=input_hashes,
            approval=approval,
            previous=previous,
            recovered_attempts=recovered_attempts,
            attempt=terminal_attempt,
            artifacts=(*run_records, *source_records, *recovered_artifacts, *attempt_records),
            source_records=source_records,
            agent_context=agent_context,
        )
        return ExecutionResult(
            attempt_id=attempt_id,
            execution_key=execution_key,
            status=status,
            qc=qc,
            reused=False,
        )

    def _reuse_completed_attempt(
        self,
        *,
        run_id: str,
        plan: AnalysisPlan,
        revision: int,
        plan_hash: str,
        input_hashes: Mapping[str, str],
        validation: DatasetValidation,
        spec: ToolSpec,
        approval: ApprovalRecord,
        previous: RunManifest | None,
        run_records: Sequence[ArtifactRecord],
        source_records: Sequence[ArtifactRecord],
        snapshot_paths: tuple[Path, Path],
        execution_key: str,
        agent_context: AgentContext | None,
    ) -> ExecutionResult | None:
        if (
            previous is None
            or previous.status is not RunStatus.COMPLETED
            or str(previous.dataset_id) != plan.dataset_id
            or previous.plan_hash != plan_hash
            or dict(previous.input_hashes) != dict(input_hashes)
            or previous.tool != plan.tool
        ):
            return None
        current_attempt = next(
            (attempt for attempt in previous.attempts if attempt.attempt_id == previous.attempt_id),
            None,
        )
        if current_attempt is None or current_attempt.status is not RunStatus.COMPLETED:
            return None
        attempt_id = str(current_attempt.attempt_id)
        attempt_dir = self._artifact_manager.resolve(run_id, f"attempts/{attempt_id}")
        if not self._parameters_match(
            attempt_dir / "parameters.json",
            plan=plan,
            snapshot_paths=snapshot_paths,
            attempt_dir=attempt_dir,
        ):
            return None
        evidence_paths = (
            f"attempts/{attempt_id}/parameters.json",
            f"attempts/{attempt_id}/logs/stdout.log",
            f"attempts/{attempt_id}/logs/stderr.log",
            *(f"attempts/{attempt_id}/{name}" for name in spec.required_artifacts),
        )
        recorded = {item.relative_path: item.sha256 for item in previous.artifacts}
        for artifact_id in evidence_paths:
            path = self._artifact_manager.resolve(run_id, artifact_id)
            if not path.is_file():
                return None
            old_digest = recorded.get(artifact_id)
            if old_digest is not None and old_digest != self._file_sha256(path):
                return None
        qc = self._validate_outputs(plan, validation, spec, attempt_dir)
        if qc.status is QCStatus.FAIL:
            return None
        updated_attempt = current_attempt.model_copy(update={"qc": qc})
        self._write_attempt(run_id, updated_attempt)
        qc_record = self._artifact_manager.write_json(
            run_id,
            f"attempts/{attempt_id}/qc.json",
            cast(JsonValue, qc.model_dump(mode="json")),
        )
        collected = self._collect_attempt_records(run_id, attempt_id, spec)
        attempts = tuple(
            updated_attempt if item.attempt_id == updated_attempt.attempt_id else item
            for item in previous.attempts
        )
        manifest = RunManifest.model_validate(
            {
                "run_id": run_id,
                "dataset_id": plan.dataset_id,
                "attempt_id": attempt_id,
                "plan_revision": revision,
                "plan_hash": plan_hash,
                "input_hashes": input_hashes,
                "tool": plan.tool,
                "software_versions": self._software_versions,
                "git_commit": self._git_commit,
                "comparison": plan.comparison,
                "alpha": plan.options.alpha,
                "lfc_shrink": plan.options.lfc_shrink,
                "random_seed": plan.options.random_seed,
                "started_at": updated_attempt.started_at,
                "ended_at": updated_attempt.ended_at,
                "status": RunStatus.COMPLETED,
                "qc": qc,
                "approvals": self._merge_approvals(previous.approvals, approval),
                "attempts": attempts,
                "artifacts": self._merge_artifacts(
                    previous.artifacts,
                    (*run_records, *source_records, qc_record, *collected),
                ),
                "source_id": agent_context.source_id if agent_context is not None else None,
                "source_artifacts": tuple(source_records),
                "agent_context": agent_context,
            }
        )
        self._artifact_manager.write_manifest(run_id, manifest)
        return ExecutionResult(
            attempt_id=attempt_id,
            execution_key=execution_key,
            status=RunStatus.COMPLETED,
            qc=qc,
            reused=True,
        )

    def _parameters_match(
        self,
        path: Path,
        *,
        plan: AnalysisPlan,
        snapshot_paths: tuple[Path, Path],
        attempt_dir: Path,
    ) -> bool:
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
            expected = {
                "counts_path": self._project_relative(snapshot_paths[0]),
                "metadata_path": self._project_relative(snapshot_paths[1]),
                "output_dir": self._project_relative(attempt_dir),
                "factor": plan.comparison.factor,
                "numerator": plan.comparison.numerator,
                "denominator": plan.comparison.denominator,
                "alpha": plan.options.alpha,
                "lfc_shrink": plan.options.lfc_shrink,
            }
        except (OSError, UnicodeError, ValueError):
            return False
        return payload == expected

    def _project_relative(self, path: Path) -> str:
        resolved = path.resolve()
        if resolved == self._project_root or self._project_root not in resolved.parents:
            raise ValueError("execution evidence must be inside project root")
        return resolved.relative_to(self._project_root).as_posix()

    def _validate_outputs(
        self,
        plan: AnalysisPlan,
        validation: DatasetValidation,
        spec: ToolSpec,
        attempt_dir: Path,
    ) -> QCReport:
        return validate_deseq2_outputs(
            spec=spec,
            attempt_dir=attempt_dir,
            expected_feature_ids=tuple(str(value) for value in validation.counts.index),
            expected_sample_ids=tuple(str(value) for value in validation.counts.columns),
            alpha=plan.options.alpha,
        )

    def _finish_attempt(
        self,
        run_id: str,
        attempt: AttemptRecord,
        spec: ToolSpec,
    ) -> tuple[ArtifactRecord, ...]:
        attempt_id = str(attempt.attempt_id)
        qc = attempt.qc
        if qc is None:
            raise ValueError("terminal attempt must include QC")
        self._artifact_manager.write_json(
            run_id,
            f"attempts/{attempt_id}/qc.json",
            cast(JsonValue, qc.model_dump(mode="json")),
        )
        self._write_attempt(run_id, attempt)
        return self._collect_attempt_records(run_id, attempt_id, spec)

    def _write_attempt(self, run_id: str, attempt: AttemptRecord) -> ArtifactRecord:
        return self._artifact_manager.write_json(
            run_id,
            f"attempts/{attempt.attempt_id}/attempt.json",
            cast(JsonValue, attempt.model_dump(mode="json")),
        )

    def _collect_attempt_records(
        self,
        run_id: str,
        attempt_id: str,
        spec: ToolSpec,
    ) -> tuple[ArtifactRecord, ...]:
        candidates = (
            f"attempts/{attempt_id}/parameters.json",
            f"attempts/{attempt_id}/attempt.json",
            f"attempts/{attempt_id}/qc.json",
            f"attempts/{attempt_id}/logs/stdout.log",
            f"attempts/{attempt_id}/logs/stderr.log",
            *(f"attempts/{attempt_id}/{name}" for name in spec.required_artifacts),
        )
        records: list[ArtifactRecord] = []
        for artifact_id in candidates:
            path = self._artifact_manager.resolve(run_id, artifact_id)
            if path.is_file():
                records.append(
                    ArtifactRecord(
                        relative_path=artifact_id,
                        sha256=self._file_sha256(path),
                    )
                )
        return tuple(records)

    def _write_terminal_manifest(
        self,
        *,
        run_id: str,
        plan: AnalysisPlan,
        revision: int,
        plan_hash: str,
        input_hashes: Mapping[str, str],
        approval: ApprovalRecord,
        previous: RunManifest | None,
        recovered_attempts: Sequence[AttemptRecord],
        attempt: AttemptRecord,
        artifacts: Sequence[ArtifactRecord],
        source_records: Sequence[ArtifactRecord],
        agent_context: AgentContext | None,
    ) -> None:
        prior_approvals = previous.approvals if previous is not None else ()
        prior_attempts = previous.attempts if previous is not None else ()
        prior_artifacts = previous.artifacts if previous is not None else ()
        qc = attempt.qc
        if qc is None or attempt.ended_at is None:
            raise ValueError("terminal attempt must be complete")
        manifest = RunManifest.model_validate(
            {
                "run_id": run_id,
                "dataset_id": plan.dataset_id,
                "attempt_id": attempt.attempt_id,
                "plan_revision": revision,
                "plan_hash": plan_hash,
                "input_hashes": input_hashes,
                "tool": plan.tool,
                "software_versions": self._software_versions,
                "git_commit": self._git_commit,
                "comparison": plan.comparison,
                "alpha": plan.options.alpha,
                "lfc_shrink": plan.options.lfc_shrink,
                "random_seed": plan.options.random_seed,
                "started_at": attempt.started_at,
                "ended_at": attempt.ended_at,
                "status": attempt.status,
                "qc": qc,
                "approvals": self._merge_approvals(prior_approvals, approval),
                "attempts": (*prior_attempts, *recovered_attempts, attempt),
                "artifacts": self._merge_artifacts(prior_artifacts, artifacts),
                "source_id": agent_context.source_id if agent_context is not None else None,
                "source_artifacts": tuple(source_records),
                "agent_context": agent_context,
            }
        )
        self._artifact_manager.write_manifest(run_id, manifest)

    def _approval_record(
        self,
        approval: Mapping[str, object],
        revision: int,
        plan_hash: str,
    ) -> ApprovalRecord:
        actor_value = approval.get("actor")
        if not isinstance(actor_value, str) or not actor_value:
            raise ExecutionRejectedError("APPROVAL_INVALID")
        decided_value = approval.get("decided_at")
        if isinstance(decided_value, str):
            try:
                decided_at = datetime.fromisoformat(decided_value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ExecutionRejectedError("APPROVAL_INVALID") from error
            if decided_at.tzinfo is None:
                raise ExecutionRejectedError("APPROVAL_INVALID")
        else:
            raise ExecutionRejectedError("APPROVAL_INVALID")
        return ApprovalRecord(
            decision="APPROVED",
            actor=actor_value,
            decided_at=decided_at,
            plan_revision=revision,
            plan_hash=plan_hash,
        )

    def _load_manifest(self, run_id: str) -> RunManifest | None:
        path = self._artifact_manager.resolve(run_id, "manifest.json")
        if not path.is_file():
            return None
        try:
            return RunManifest.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as error:
            raise ExecutionRejectedError("MANIFEST_INVALID") from error

    @staticmethod
    def _bind_existing_run(
        previous: RunManifest | None,
        run_id: str,
        plan: AnalysisPlan,
        input_hashes: Mapping[str, str],
        agent_context: AgentContext | None = None,
    ) -> None:
        if previous is None:
            return
        if str(previous.run_id) != run_id:
            raise ExecutionRejectedError("MANIFEST_RUN_ID_MISMATCH")
        if str(previous.dataset_id) != plan.dataset_id:
            raise ExecutionRejectedError("RUN_DATASET_MISMATCH")
        if dict(previous.input_hashes) != dict(input_hashes):
            raise ExecutionRejectedError("RUN_INPUT_HASH_MISMATCH")
        if previous.agent_context != agent_context:
            raise ExecutionRejectedError("RUN_AGENT_CONTEXT_MISMATCH")
        previous_source_id = previous.source_id
        current_source_id = agent_context.source_id if agent_context is not None else None
        if previous_source_id != current_source_id:
            raise ExecutionRejectedError("RUN_SOURCE_ID_MISMATCH")

    def _source_records(
        self,
        run_id: str,
        agent_context: AgentContext | None,
        dataset_id: str,
    ) -> tuple[ArtifactRecord, ...]:
        if agent_context is None or agent_context.source_id is None:
            return ()
        source_files = (
            ("source/raw/source.bin", "raw_sha256"),
            ("source/source.json", None),
            ("source/normalized/counts.csv", "counts_sha256"),
            ("source/normalized/metadata.csv", "metadata_sha256"),
        )
        source_json_path = self._artifact_manager.resolve(run_id, "source/source.json")
        try:
            payload = json.loads(source_json_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            raise ExecutionRejectedError("SOURCE_ARTIFACT_TAMPERED") from error
        if not isinstance(payload, Mapping):
            raise ExecutionRejectedError("SOURCE_ARTIFACT_TAMPERED")
        if payload.get("source_id") != str(agent_context.source_id):
            raise ExecutionRejectedError("SOURCE_ID_MISMATCH")
        if payload.get("dataset_id") != dataset_id:
            raise ExecutionRejectedError("SOURCE_DATASET_MISMATCH")
        records: list[ArtifactRecord] = []
        for artifact_id, digest_key in source_files:
            path = self._artifact_manager.resolve(run_id, artifact_id)
            if not path.is_file():
                raise ExecutionRejectedError("SOURCE_ARTIFACT_MISSING")
            digest = self._file_sha256(path)
            if digest_key is not None and payload.get(digest_key) != digest:
                raise ExecutionRejectedError("SOURCE_ARTIFACT_TAMPERED")
            records.append(ArtifactRecord(relative_path=artifact_id, sha256=digest))
        return tuple(records)

    @staticmethod
    def _agent_context(state: Mapping[str, object]) -> AgentContext | None:
        value = state.get("agent_context")
        if value is None:
            return None
        try:
            return AgentContext.model_validate(value)
        except ValidationError as error:
            raise ExecutionRejectedError("AGENT_CONTEXT_INVALID") from error

    def _recover_orphan_attempts(
        self,
        *,
        run_id: str,
        spec: ToolSpec,
        previous: RunManifest | None,
    ) -> tuple[tuple[AttemptRecord, ...], tuple[ArtifactRecord, ...]]:
        attempts_root = self._artifact_manager.resolve(run_id, "attempts")
        referenced = {
            str(attempt.attempt_id) for attempt in (() if previous is None else previous.attempts)
        }
        recovered: list[AttemptRecord] = []
        artifacts: list[ArtifactRecord] = []
        for attempt_dir in sorted(attempts_root.iterdir(), key=lambda path: path.name):
            if not attempt_dir.is_dir() or attempt_dir.name in referenced:
                continue
            attempt_path = attempt_dir / "attempt.json"
            try:
                attempt = AttemptRecord.model_validate_json(attempt_path.read_bytes())
            except (OSError, ValidationError, ValueError) as error:
                raise ExecutionRejectedError("ATTEMPT_RECORD_INVALID") from error
            if str(attempt.attempt_id) != attempt_dir.name:
                raise ExecutionRejectedError("ATTEMPT_RECORD_INVALID")
            if attempt.status is RunStatus.RUNNING:
                qc = QCReport(
                    status=QCStatus.FAIL,
                    issues=(
                        QCIssue(
                            code="EXECUTION_INTERRUPTED",
                            status=QCStatus.FAIL,
                            message="execution was interrupted before a terminal record",
                        ),
                    ),
                )
                attempt = AttemptRecord(
                    attempt_id=attempt.attempt_id,
                    started_at=attempt.started_at,
                    ended_at=max(self._now(), attempt.started_at),
                    status=RunStatus.FAILED,
                    qc=qc,
                )
                artifacts.extend(self._finish_attempt(run_id, attempt, spec))
            elif (
                attempt.status
                not in {
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                }
                or attempt.ended_at is None
                or attempt.qc is None
            ):
                raise ExecutionRejectedError("ATTEMPT_RECORD_INVALID")
            else:
                artifacts.extend(self._collect_attempt_records(run_id, attempt_dir.name, spec))
            recovered.append(attempt)
        return tuple(recovered), tuple(artifacts)

    def _execution_failure_qc(self, error: Exception) -> QCReport:
        code = error.code if isinstance(error, RRunnerError) else "EXECUTION_FAILED"
        issue = QCIssue(
            code=code,
            status=QCStatus.FAIL,
            message="execution did not produce a reusable completed attempt",
            evidence={"error_type": type(error).__name__},
        )
        return QCReport(status=QCStatus.FAIL, issues=(issue,))

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _merge_approvals(
        previous: Sequence[ApprovalRecord], current: ApprovalRecord
    ) -> tuple[ApprovalRecord, ...]:
        if current in previous:
            return tuple(previous)
        return (*previous, current)

    @staticmethod
    def _merge_artifacts(
        previous: Sequence[ArtifactRecord], current: Sequence[ArtifactRecord]
    ) -> tuple[ArtifactRecord, ...]:
        # A prior HTML report does not attest to this execution or plan revision.
        # Keep its bytes for diagnosis; only the reporter can register it again.
        merged = {
            record.relative_path: record
            for record in previous
            if record.relative_path != "report/report.html"
        }
        merged.update({record.relative_path: record for record in current})
        return tuple(merged.values())

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
