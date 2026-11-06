"""Owner-bound single matrix import into the existing approval-gated workflow."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from bioagent.api.workbench_owner import workbench_owner_hash
from bioagent.api.workbench_routes import Deps
from bioagent.domain.plans import AnalysisPlan
from bioagent.services.datasets import DatasetImportError
from bioagent.services.matrices import MatrixConfirmation, MatrixService
from bioagent.workbench.models import TurnStatus, WorkbenchError

router = APIRouter(prefix="/api/v1/workbench/conversations/{chat}/matrices")


@router.get("/{identity}/results")
def results(chat: UUID, identity: UUID, request: Request, deps: Deps) -> dict[str, Any]:
    import csv
    import math

    from bioagent.api.routes import _manifest

    store = service(chat, request, deps)
    with store.db() as db:
        _, record = store.read(db, str(chat), str(identity))
    if "run_id" not in record:
        return {"status": record["status"]}
    state = deps.analysis_service.read_run(record["run_id"])
    if state["status"] != "COMPLETED":
        return {"status": state["status"]}
    manifest = _manifest(record["run_id"], deps)
    artifact = next(a for a in manifest.artifacts if a.relative_path.endswith("/all_results.csv"))
    path = deps.artifact_manager.resolve(record["run_id"], artifact.relative_path)
    if sha256(path.read_bytes()).hexdigest() != artifact.sha256:
        raise DatasetImportError("MATRIX_RESULT_INTEGRITY_FAILED", status_code=409)
    up = down = tested = total = 0
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            total += 1
            try:
                padj, fold = float(row["padj"]), float(row["log2FoldChange"])
            except ValueError:
                continue
            if math.isfinite(padj):
                tested += 1
                if padj <= manifest.alpha:
                    up += int(fold > 0)
                    down += int(fold < 0)
    return {
        "status": "COMPLETED",
        "run_id": record["run_id"],
        "comparison": manifest.comparison,
        "alpha": manifest.alpha,
        "genes": total,
        "adjusted_p_available": tested,
        "significant_up": up,
        "significant_down": down,
        "qc": manifest.qc.model_dump(mode="json"),
        "result_sha256": artifact.sha256,
        "interpretation": (
            "方向为实验组相对对照组；显著性不等于因果或临床结论。请结合QC、图表和完整报告核查。"
        ),
    }


def service(chat: UUID, request: Request, deps: Any) -> MatrixService:
    owner = workbench_owner_hash(request)
    if not owner or not deps.workbench.owns_conversation(chat, owner):
        raise WorkbenchError("KNOWLEDGE_TURN_MISMATCH")
    return MatrixService(deps.settings.data_dir / "matrices.sqlite", deps.dataset_import_service)


@router.post("", status_code=201)
async def upload(chat: UUID, request: Request, file: UploadFile, deps: Deps) -> dict[str, Any]:
    limit = deps.dataset_import_service.upload_limits.max_bytes
    raw = await file.read(limit + 1)

    def persist() -> dict[str, Any]:
        store = service(chat, request, deps)
        return store.upload(str(chat), raw, Path(file.filename or "").suffix.lower())

    return await run_in_threadpool(persist)


@router.get("")
def latest(chat: UUID, request: Request, deps: Deps) -> dict[str, Any] | None:
    return service(chat, request, deps).latest(str(chat))


@router.get("/{identity}")
def get(
    chat: UUID,
    identity: UUID,
    request: Request,
    deps: Deps,
    direction: Literal["genes_rows", "samples_rows"] = "genes_rows",
) -> dict[str, Any]:
    return service(chat, request, deps).get(str(chat), str(identity), direction)


@router.post("/{identity}/confirm")
def confirm(
    chat: UUID, identity: UUID, payload: MatrixConfirmation, request: Request, deps: Deps
) -> dict[str, Any]:
    store = service(chat, request, deps)
    canonical = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    fingerprint = sha256(canonical.encode()).hexdigest()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        raw, record = store.read(db, str(chat), str(identity))
        if "confirmation_hash" in record:
            # Compare the saved scientific request, including pre-canonicalization records.
            saved = json.dumps(
                record.get("confirmation"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            if saved != canonical:
                raise DatasetImportError("MATRIX_CONFIRMATION_CONFLICT", status_code=409)
            if record["status"] != "CONFIRMED":
                raise DatasetImportError("MATRIX_PLANNING_INTERRUPTED_OR_FAILED", status_code=409)
            deps.dataset_repository.paths(record["dataset_id"])
            return record
        if payload.revision != record["revision"]:
            raise DatasetImportError("MATRIX_REVISION_CONFLICT", status_code=409)
        counts, metadata = store.normalize(raw, record["suffix"], payload)
        if deps.workbench.active_turn(chat) is not None:
            raise WorkbenchError("TURN_BUSY")
        prepared = deps.turn_service._prepare(payload.profile_id, None)
        if prepared.planner is None:
            raise WorkbenchError("MODEL_NOT_CONFIGURED")
        dataset_id = deps.dataset_import_service.import_uploaded(counts, metadata, ".csv", ".csv")
        turn = deps.workbench.begin_turn(
            chat,
            uuid4(),
            payload.goal,
            prepared.snapshot,
            dataset_ids=(UUID(dataset_id),),
            profile_id=payload.profile_id,
        )
        deps.workbench.update_turn(turn.id, TurnStatus.RUNNING)
        record.update(
            status="PLANNING",
            confirmation=json.loads(canonical),
            confirmation_hash=fingerprint,
            dataset_id=dataset_id,
            counts_sha256=sha256(counts).hexdigest(),
            metadata_sha256=sha256(metadata).hexdigest(),
            turn_id=str(turn.id),
        )
        db.execute("UPDATE matrices SET record=? WHERE id=?", (json.dumps(record), str(identity)))
        db.commit()
        planner = prepared.planner

        class ConfirmedPlanner:
            def plan(self, *, user_goal: str, summary: Any) -> AnalysisPlan:
                value = AnalysisPlan.model_validate(
                    planner.plan(user_goal=user_goal, summary=summary)
                )
                if (
                    str(value.dataset_id) != dataset_id
                    or value.comparison.factor != "condition"
                    or value.comparison.numerator != payload.numerator
                    or value.comparison.denominator != payload.denominator
                ):
                    raise DatasetImportError("MATRIX_PLANNER_COMPARISON_MISMATCH")
                return value

        @contextmanager
        def publication(run_id: str) -> Iterator[bool]:
            with deps.workbench.matrix_plan_publication(turn.id, UUID(run_id)) as publish:
                yield publish
                record.update(status="CONFIRMED" if publish else "CANCELLED", run_id=run_id)

        try:
            deps.analysis_service.create_run(
                dataset_id=dataset_id,
                goal=(
                    f"{payload.goal}\nConfirmed comparison: {payload.numerator} "
                    f"relative to {payload.denominator}; factor condition."
                ),
                planner=ConfirmedPlanner(),
                publication_guard=publication,
                agent_context={
                    "conversation_id": str(chat),
                    "turn_id": str(turn.id),
                    "model_snapshot": prepared.snapshot.model_dump(mode="json"),
                },
            )
        except Exception:
            record["status"] = "FAILED"
            record["error_code"] = "MATRIX_PLANNING_FAILED"
            deps.workbench.fail_turn(turn.id, "MATRIX_PLANNING_FAILED")
            raise
        finally:
            # Commit independently: re-raising must not roll back the terminal record.
            with store.db() as terminal_db:
                terminal_db.execute(
                    "UPDATE matrices SET record=? WHERE id=?", (json.dumps(record), str(identity))
                )
    return record
