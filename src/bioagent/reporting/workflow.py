from hashlib import sha256

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import RunManifest
from bioagent.domain.plans import AnalysisPlan
from bioagent.execution.controller import calculate_plan_hash
from bioagent.reporting.generator import ReportGenerator, ReportSummary
from bioagent.workflow.state import WorkflowState


class ArtifactReporter:
    """Publish a deterministic report from the current execution's verified bytes."""

    def __init__(self, artifacts: ArtifactManager) -> None:
        self._artifacts = artifacts

    def __call__(self, state: WorkflowState) -> dict[str, object]:
        try:
            run_id = state["run_id"]
            manifest = RunManifest.model_validate_json(
                self._artifacts.resolve(run_id, "manifest.json").read_bytes()
            )
            plan = AnalysisPlan.model_validate(state["plan"])
            if (
                state.get("status") != "RUNNING"
                or manifest.status.value != "COMPLETED"
                or str(manifest.run_id) != run_id
                or str(manifest.dataset_id) != state.get("dataset_id")
                or str(manifest.attempt_id) != state.get("attempt_id")
                or manifest.plan_revision != state.get("plan_revision")
                or manifest.plan_hash != calculate_plan_hash(plan)
                or manifest.qc.model_dump(mode="json") != state.get("qc")
            ):
                raise ValueError("report does not match workflow execution")
            for record in manifest.artifacts:
                content = self._artifacts.resolve(run_id, record.relative_path).read_bytes()
                if sha256(content).hexdigest() != record.sha256:
                    raise ValueError("report artifact hash mismatch")
            prefix = f"attempts/{manifest.attempt_id}/results/"
            summary = ReportSummary.from_artifacts(
                manifest=manifest,
                execution_summary_bytes=self._artifacts.resolve(
                    run_id, prefix + "execution_summary.json"
                ).read_bytes(),
                all_results_bytes=self._artifacts.resolve(
                    run_id, prefix + "all_results.csv"
                ).read_bytes(),
            )
            html = ReportGenerator().render(
                manifest=manifest,
                qc=manifest.qc,
                summary=summary,
                narrative=None,
            )
            record = self._artifacts.write_bytes(run_id, "report/report.html", html.encode())
            payload = manifest.model_dump(mode="python")
            payload["artifacts"] = (
                *(
                    item
                    for item in manifest.artifacts
                    if item.relative_path != record.relative_path
                ),
                record,
            )
            self._artifacts.write_manifest(run_id, RunManifest.model_validate(payload))
        except Exception:
            return {"status": "FAILED", "error": {"code": "REPORT_FAILED"}}
        return {"report": {"status": "completed", "relative_path": record.relative_path}}
