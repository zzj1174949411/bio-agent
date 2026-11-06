from hashlib import sha256
from pathlib import Path

import pytest
from test_generator import (
    _ALL_RESULTS_BYTES,
    _execution_summary_bytes,
    _manifest,
    _warn_qc,
)

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import RunManifest
from bioagent.domain.plans import AnalysisPlan
from bioagent.execution.controller import calculate_plan_hash
from bioagent.reporting.workflow import ArtifactReporter


@pytest.mark.parametrize("failure", [None, "attempt", "plan", "tamper", "render"])
def test_report_publication_fails_closed(tmp_path: Path, monkeypatch, failure) -> None:
    manager = ArtifactManager(tmp_path)
    manifest = _manifest(_warn_qc())
    run_id = str(manifest.run_id)
    (tmp_path / run_id).mkdir()
    plan = AnalysisPlan(
        dataset_id=str(manifest.dataset_id), comparison=manifest.comparison.model_dump()
    )
    payload = manifest.model_dump(mode="python")
    payload["plan_hash"] = calculate_plan_hash(plan)
    payload["approvals"] = tuple(
        item.model_copy(update={"plan_hash": payload["plan_hash"]}) for item in manifest.approvals
    )
    records = []
    for item in manifest.artifacts:
        content = (
            _ALL_RESULTS_BYTES
            if item.relative_path.endswith("all_results.csv")
            else _execution_summary_bytes("AD")
            if item.relative_path.endswith(".json")
            else b"png"
        )
        records.append(manager.write_bytes(run_id, item.relative_path, content))
    payload["artifacts"] = records
    manifest = RunManifest.model_validate(payload)
    manager.write_manifest(run_id, manifest)
    before = manager.resolve(run_id, "manifest.json").read_bytes()
    state = {
        "run_id": run_id,
        "dataset_id": str(manifest.dataset_id),
        "attempt_id": str(manifest.attempt_id),
        "plan_revision": 1,
        "plan": plan.model_dump(mode="json"),
        "qc": manifest.qc.model_dump(mode="json"),
        "status": "RUNNING",
    }
    if failure == "attempt":
        state["attempt_id"] = run_id
    if failure == "plan":
        state["plan"]["options"]["alpha"] = 0.1
    if failure == "tamper":
        manager.resolve(run_id, records[0].relative_path).write_bytes(b"changed")
    if failure == "render":

        def fail(*args, **kwargs):
            raise RuntimeError("private diagnostic should not escape")

        monkeypatch.setattr("bioagent.reporting.workflow.ReportGenerator.render", fail)
    reporter = ArtifactReporter(manager)
    result = reporter(state)
    if failure:
        assert result == {"status": "FAILED", "error": {"code": "REPORT_FAILED"}}
        assert manager.resolve(run_id, "manifest.json").read_bytes() == before
        assert not manager.resolve(run_id, "report/report.html").exists()
    else:
        assert result["report"]["status"] == "completed"
        updated = RunManifest.model_validate_json(
            manager.resolve(run_id, "manifest.json").read_bytes()
        )
        record = next(
            item for item in updated.artifacts if item.relative_path == "report/report.html"
        )
        assert (
            record.sha256
            == sha256(manager.resolve(run_id, record.relative_path).read_bytes()).hexdigest()
        )
        assert reporter(state) == result
