"""Real R parity: new single-matrix HTTP path versus old paired import."""

import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.domain.plans import AnalysisPlan
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.turns import PreparedChat

ROOT = Path(__file__).resolve().parents[2]


class Planner:
    def plan(self, *, user_goal, summary):
        return AnalysisPlan(
            dataset_id=summary.dataset_id,
            comparison={"factor": "condition", "numerator": "AD", "denominator": "Control"},
            options={"lfc_shrink": False},
        )


def make_app(tmp_path):
    async def stream(messages):
        yield "Mock"

    def prepare(*_):
        return PreparedChat(
            TurnModelSnapshot(
                provider="ollama",
                model="mock",
                base_url="http://localhost:11434",
                revision=1,
                structured_method="function_calling",
                thinking="default",
            ),
            stream,
            planner=Planner(),
        )

    return create_app(
        Settings(
            _env_file=None,
            deepseek_api_key=None,
            data_dir=tmp_path / "data",
            runs_dir=tmp_path / "runs",
            checkpoint_db=tmp_path / "cp.sqlite",
            workbench_db=tmp_path / "wb.sqlite",
        ),
        {"planner": Planner(), "chat_model_factory": prepare},
    )


def setup(client):
    client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
    project = client.post("/api/v1/workbench/projects", json={"title": "synthetic"}).json()
    chat = client.post(
        "/api/v1/workbench/conversations", json={"project_id": project["id"], "title": "matrix"}
    ).json()["id"]
    return f"/api/v1/workbench/conversations/{chat}/matrices"


def confirmation():
    return {
        "revision": 1,
        "direction": "genes_rows",
        "id_column": 0,
        "sample_columns": list(range(1, 7)),
        "groups": {str(i): "Control" if i < 4 else "AD" for i in range(1, 7)},
        "numerator": "AD",
        "denominator": "Control",
        "data_type": "RAW_COUNTS",
        "source": "Self authored synthetic raw counts; not normalized",
        "goal": "Compare AD relative to Control",
        "profile_id": str(uuid4()),
    }


def test_single_matrix_real_r_equals_paired_path(tmp_path, monkeypatch):
    libraries = sorted((ROOT / "renv/library").glob("*/R-*/**/DESeq2"))
    if libraries:
        monkeypatch.setenv("R_LIBS", str(libraries[0].parent))
        monkeypatch.setenv("RENV_CONFIG_AUTOLOADER_ENABLED", "FALSE")
    from bioagent.execution.r_runner import RRunner

    original_run = RRunner.run
    invocations = []

    def tracked(self, *args, **kwargs):
        invocations.append("Rscript")
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(RRunner, "run", tracked)
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        prefix = setup(client)
        raw = (
            (ROOT / "tests/fixtures/counts_deseq2.csv")
            .read_bytes()
            .replace(b"feature_id", b"gene_symbol", 1)
        )
        uploaded = client.post(prefix, files={"file": ("matrix.csv", raw, "text/csv")})
        assert uploaded.status_code == 201, uploaded.text
        target = prefix + "/" + uploaded.json()["id"] + "/confirm"
        response = client.post(target, json=confirmation())
        assert response.status_code == 200, response.text
        record = response.json()
        run = record["run_id"]
        assert not list((tmp_path / "runs" / run / "attempts").glob("*"))
        assert invocations == []
        old = client.post(
            "/api/v1/datasets",
            files={
                name: (
                    name + ".csv",
                    (ROOT / f"tests/fixtures/{name}_deseq2.csv").read_bytes(),
                    "text/csv",
                )
                for name in ("counts", "metadata")
            },
        ).json()["dataset_id"]
        old_run = client.post(
            "/api/v1/runs", json={"dataset_id": old, "goal": "Compare AD relative to Control"}
        ).json()["run_id"]
        results = []
        for identity in (run, old_run):
            approved = client.post(
                f"/api/v1/runs/{identity}/approval", json={"action": "approve", "plan_revision": 1}
            )
            assert approved.status_code == 202, approved.text
            app.state.dependencies.job_runner.wait(approved.json()["job_id"], timeout=120)
            state = client.get(f"/api/v1/runs/{identity}").json()
            assert state["status"] == "COMPLETED", state
            files = {}
            for item in client.get(f"/api/v1/runs/{identity}/artifacts").json()["artifacts"]:
                downloaded = client.get(f"/api/v1/runs/{identity}/artifacts/{item['artifact_id']}")
                assert sha256(downloaded.content).hexdigest() == item["sha256"]
                files[item["name"]] = downloaded.content
            manifest = json.loads(files["manifest.json"])
            assert manifest["comparison"]["numerator"] == "AD"
            assert {
                "report.html",
                "pca.png",
                "sample_correlation_heatmap.png",
                "ma_plot.png",
                "volcano_plot.png",
            } <= files.keys()
            if identity == run:
                assert manifest["input_hashes"]["counts"] == record["counts_sha256"]
                assert manifest["input_hashes"]["metadata"] == record["metadata_sha256"]
            from io import BytesIO

            table_name = next(n for n in files if n == "all_results.csv")
            results.append(pd.read_csv(BytesIO(files[table_name])).sort_values("feature_id"))
        summary = client.get(target.removesuffix("/confirm") + "/results").json()
        assert summary["genes"] == len(results[0]) and summary["status"] == "COMPLETED"
        assert len(invocations) == 2
        assert list(results[0]["feature_id"]) == list(results[1]["feature_id"])
        for column in ["log2FoldChange", "pvalue", "padj"]:
            np.testing.assert_allclose(
                results[0][column], results[1][column], rtol=1e-8, atol=1e-10, equal_nan=True
            )

        (tmp_path / "acceptance.json").write_text(
            json.dumps(
                {
                    "r_calls": len(invocations),
                    "new_run": run,
                    "old_run": old_run,
                    "summary": summary,
                    "genes": len(results[0]),
                    "comparison": "AD relative to Control",
                    "numeric_parity": True,
                    "rtol": 1e-8,
                    "atol": 1e-10,
                }
            ),
            encoding="utf-8",
        )
