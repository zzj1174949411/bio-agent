"""Deterministic HTTP summary, significant-table and report threshold agreement."""

import json
import sys
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bioagent.api import matrix_routes, routes
from bioagent.api.dependencies import get_dependencies
from bioagent.artifacts.manifest import RunManifest
from bioagent.domain.qc import QCStatus
from bioagent.reporting.generator import ReportGenerator, ReportSummary
from bioagent.tools.deseq2 import validate_deseq2_outputs

sys.path.insert(0, str(Path(__file__).parents[1]))
from test_deseq2_runner import (  # noqa: E402
    ALPHA,
    FEATURE_IDS,
    SAMPLE_IDS,
    _write_valid_outputs,
)


def test_matrix_summary_matches_significant_table_and_report_at_alpha(tmp_path, monkeypatch):
    spec = _write_valid_outputs(tmp_path)
    results_path = tmp_path / "results/all_results.csv"
    table = pd.read_csv(results_path)
    table["padj"] = ALPHA
    table["pvalue"] = [0.01, 0.02]
    table.to_csv(results_path, index=False)
    # Both rows are significant under the existing R <= alpha contract.
    table.to_csv(tmp_path / "results/significant_results.csv", index=False)
    qc = validate_deseq2_outputs(
        spec=spec,
        attempt_dir=tmp_path,
        expected_feature_ids=FEATURE_IDS,
        expected_sample_ids=SAMPLE_IDS,
        alpha=ALPHA,
    )
    assert qc.status is QCStatus.PASS

    run_id, attempt_id = uuid4(), uuid4()
    started = datetime(2026, 10, 23, tzinfo=UTC)
    summary_bytes = json.dumps(
        {
            "status": "success",
            "factor": "condition",
            "numerator": "AD",
            "denominator": "Control",
            "alpha": ALPHA,
            "lfc_shrink": False,
            "n_features": 2,
            "n_samples": 2,
            "significant_count": 2,
        }
    ).encode()
    result_bytes = results_path.read_bytes()
    result_relative = f"attempts/{attempt_id}/results/all_results.csv"
    manifest = RunManifest(
        run_id=run_id,
        dataset_id=uuid4(),
        attempt_id=attempt_id,
        plan_revision=1,
        plan_hash="a" * 64,
        input_hashes={"counts": "b" * 64, "metadata": "c" * 64},
        tool="deseq2",
        software_versions={"r": "4.5.2", "deseq2": "1.50.2"},
        git_commit="d" * 40,
        comparison={"factor": "condition", "numerator": "AD", "denominator": "Control"},
        alpha=ALPHA,
        lfc_shrink=False,
        random_seed=42,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        status="COMPLETED",
        qc=qc,
        approvals=(
            {
                "decision": "APPROVED",
                "actor": "fixture",
                "decided_at": started,
                "plan_revision": 1,
                "plan_hash": "a" * 64,
            },
        ),
        attempts=(
            {
                "attempt_id": attempt_id,
                "started_at": started,
                "ended_at": started + timedelta(seconds=1),
                "status": "COMPLETED",
                "qc": qc,
            },
        ),
        artifacts=(
            {"relative_path": result_relative, "sha256": sha256(result_bytes).hexdigest()},
            {
                "relative_path": f"attempts/{attempt_id}/results/execution_summary.json",
                "sha256": sha256(summary_bytes).hexdigest(),
            },
        ),
    )
    summary = ReportSummary.from_artifacts(
        manifest=manifest,
        execution_summary_bytes=summary_bytes,
        all_results_bytes=result_bytes,
    )
    html = ReportGenerator().render(manifest=manifest, qc=qc, summary=summary, narrative=None)
    assert summary.significant_gene_count == 2
    assert "<strong>Significant genes:</strong> 2" in html

    # Isolate result aggregation from ownership/storage setup; those boundaries
    # have their own API tests. No worker, model or R process runs in this fixture.
    store = SimpleNamespace(
        db=lambda: nullcontext(None),
        read=lambda *_: ({}, {"run_id": str(run_id)}),
    )
    monkeypatch.setattr(matrix_routes, "service", lambda *_: store)
    monkeypatch.setattr(routes, "_manifest", lambda *_: manifest)
    deps = SimpleNamespace(
        analysis_service=SimpleNamespace(read_run=lambda *_: {"status": "COMPLETED"}),
        artifact_manager=SimpleNamespace(resolve=lambda *_: results_path),
    )
    app = FastAPI()
    app.include_router(matrix_routes.router)
    app.dependency_overrides[get_dependencies] = lambda: deps
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/workbench/conversations/{uuid4()}/matrices/{uuid4()}/results"
        )
    assert response.status_code == 200, response.text
    actual = response.json()
    assert actual["significant_up"] == 1
    assert actual["significant_down"] == 1
    assert actual["significant_up"] + actual["significant_down"] == summary.significant_gene_count
