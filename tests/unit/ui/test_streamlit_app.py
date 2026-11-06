from __future__ import annotations

import ast
import base64
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parents[3] / "ui" / "streamlit_app.py"
PAGES = ("New Analysis", "Plan Review", "Run Monitor", "Results", "Run History")


def _load_app_module() -> object:
    spec = importlib.util.spec_from_file_location("bioagent_streamlit_app", APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _response(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "http://api.test"),
    )


def test_api_client_uses_configured_base_url_and_fixed_timeout() -> None:
    api_client = _load_app_module().ApiClient
    transport = MagicMock(spec=httpx.Client)

    with (
        patch("httpx.Client", return_value=transport) as client_factory,
        api_client("http://api.test"),
    ):
        pass

    client_factory.assert_called_once_with(base_url="http://api.test", timeout=30)
    transport.close.assert_called_once_with()


def test_api_client_uses_only_declared_http_endpoints() -> None:
    api_client = _load_app_module().ApiClient
    transport = MagicMock(spec=httpx.Client)
    transport.post.side_effect = [
        _response({"dataset_id": "dataset-id"}, 201),
        _response({"run_id": "run-id", "status": "AWAITING_APPROVAL"}, 201),
        _response({"run_id": "run-id", "status": "QUEUED"}, 202),
        _response({"run_id": "run-id", "status": "CANCELLED"}),
    ]
    transport.get.side_effect = [
        _response({"dataset_id": "dataset-id", "is_valid": True}),
        _response({"run_id": "run-id", "status": "RUNNING"}),
        _response({"run_id": "run-id", "plan_revision": 1, "plan": {}}),
        _response({"run_id": "run-id", "artifacts": []}),
        _response({"runs": [], "issues": []}),
    ]

    with patch("httpx.Client", return_value=transport), api_client("http://api.test") as api:
        api.upload_dataset(
            counts_name="counts.csv",
            counts_type="text/csv",
            counts=b"feature_id,S1\nG1,1\n",
            metadata_name="metadata.csv",
            metadata_type="text/csv",
            metadata=b"sample_id,condition\nS1,A\n",
        )
        api.get_validation("dataset-id")
        api.create_run("dataset-id", "compare A with B")
        api.get_run("run-id")
        api.get_plan("run-id")
        api.approve("run-id", action="approve", plan_revision=1)
        api.cancel("run-id")
        api.list_artifacts("run-id")
        api.list_runs("RUNNING")

    upload_call = transport.post.call_args_list[0]
    assert upload_call.args == ("/api/v1/datasets",)
    assert set(upload_call.kwargs["files"]) == {"counts", "metadata"}
    assert transport.post.call_args_list[1].args == ("/api/v1/runs",)
    assert transport.post.call_args_list[2].args == ("/api/v1/runs/run-id/approval",)
    assert transport.post.call_args_list[3].args == ("/api/v1/runs/run-id/cancel",)
    assert [call.args[0] for call in transport.get.call_args_list] == [
        "/api/v1/datasets/dataset-id/validation",
        "/api/v1/runs/run-id",
        "/api/v1/runs/run-id/plan",
        "/api/v1/runs/run-id/artifacts",
        "/api/v1/runs",
    ]
    assert transport.get.call_args_list[-1].kwargs == {"params": {"status": "RUNNING"}}


def test_session_state_keeps_only_lightweight_navigation_data() -> None:
    with patch("httpx.Client", return_value=MagicMock(spec=httpx.Client)):
        app = AppTest.from_file(str(APP_PATH)).run()

    assert not app.exception
    assert app.session_state.filtered_state == {
        "dataset_id": None,
        "page": "New Analysis",
        "plan_revision": None,
        "run_id": None,
    }


def test_plan_review_shows_direction_and_submits_approval() -> None:
    run_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
    transport = MagicMock(spec=httpx.Client)
    transport.get.return_value = _response(
        {
            "run_id": run_id,
            "plan_revision": 2,
            "plan": {
                "analysis_type": "bulk_differential_expression",
                "tool": "deseq2",
                "dataset_id": "dataset-id",
                "comparison": {
                    "factor": "condition",
                    "numerator": "AD",
                    "denominator": "Control",
                },
                "options": {"alpha": 0.05, "lfc_shrink": True, "random_seed": 42},
            },
        }
    )
    transport.post.return_value = _response(
        {"run_id": run_id, "status": "QUEUED"}, 202
    )

    with patch("httpx.Client", return_value=transport):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.session_state["run_id"] = run_id
        app.sidebar.radio[0].set_value("Plan Review").run()

        assert not app.exception
        assert any(
            "AD relative to Control" in element.value for element in app.markdown
        )
        approve = next(button for button in app.button if button.label == "Approve plan")
        approve.click().run()

    assert any(
        call.args == (f"/api/v1/runs/{run_id}/approval",)
        and call.kwargs["json"] == {
            "action": "approve",
            "plan_revision": 2,
            "plan": None,
        }
        for call in transport.post.call_args_list
    )


def test_run_monitor_polls_status_and_can_cancel() -> None:
    run_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
    transport = MagicMock(spec=httpx.Client)
    transport.get.return_value = _response(
        {
            "run_id": run_id,
            "status": "RUNNING",
            "qc": {
                "status": "WARN",
                "issues": [
                    {
                        "code": "LOW_REPLICATE_NUMBER",
                        "status": "WARN",
                        "message": "Only two replicates",
                        "evidence": {},
                    }
                ],
            },
        }
    )
    transport.post.return_value = _response(
        {"run_id": run_id, "status": "CANCELLATION_REQUESTED"}, 202
    )

    with patch("httpx.Client", return_value=transport):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.session_state["run_id"] = run_id
        app.sidebar.radio[0].set_value("Run Monitor").run()

        assert not app.exception
        assert app.metric[0].value == "RUNNING"
        assert any("LOW_REPLICATE_NUMBER" in item.value for item in app.warning)
        cancel = next(button for button in app.button if button.label == "Cancel run")
        cancel.click().run()

    assert any(
        call.args == (f"/api/v1/runs/{run_id}/cancel",)
        for call in transport.post.call_args_list
    )


def test_results_show_qc_png_report_and_downloads() -> None:
    run_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    transport = MagicMock(spec=httpx.Client)

    def get(path: str) -> httpx.Response:
        if path == f"/api/v1/runs/{run_id}":
            return _response(
                {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "qc": {"status": "WARN", "issues": []},
                }
            )
        if path == f"/api/v1/runs/{run_id}/artifacts":
            return _response(
                {
                    "run_id": run_id,
                    "artifacts": [
                        {"artifact_id": "pca-id", "sha256": "a" * 64},
                        {"artifact_id": "report-id", "sha256": "b" * 64},
                    ],
                }
            )
        if path.endswith("/pca-id"):
            return httpx.Response(
                200,
                content=png,
                headers={
                    "content-type": "image/png",
                    "content-disposition": 'attachment; filename="pca.png"',
                },
                request=httpx.Request("GET", "http://api.test"),
            )
        if path.endswith("/report-id"):
            return httpx.Response(
                200,
                content=b"<html><body>Deterministic report</body></html>",
                headers={
                    "content-type": "text/html",
                    "content-disposition": 'attachment; filename="report.html"',
                },
                request=httpx.Request("GET", "http://api.test"),
            )
        raise AssertionError(f"unexpected GET {path}")

    transport.get.side_effect = get

    with patch("httpx.Client", return_value=transport):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.session_state["run_id"] = run_id
        app.sidebar.radio[0].set_value("Results").run()

    assert not app.exception
    assert any("QC: WARN" in element.value for element in app.markdown)
    assert sorted(button.label for button in app.get("download_button")) == [
        "Download pca.png",
        "Download report.html",
    ]


def test_run_history_loads_project_runs_without_session_run_ids() -> None:
    run_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
    dataset_id = "61d32f63-7c68-41df-814e-296fc47b5730"
    attempt_id = "b99fb530-a935-45d8-8ccd-c5c01c07354d"
    transport = MagicMock(spec=httpx.Client)
    transport.get.return_value = _response(
        {
            "runs": [
                {
                    "run_id": run_id,
                    "dataset_id": dataset_id,
                    "status": "COMPLETED",
                    "qc_status": "PASS",
                    "plan_revision": 2,
                    "attempt_id": attempt_id,
                    "index_updated_at": "2026-09-04T08:30:00+00:00",
                    "completed_at": "2026-09-04T08:29:58+00:00",
                    "evidence_status": "VERIFIED",
                }
            ],
            "issues": [],
        }
    )

    with patch("httpx.Client", return_value=transport):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.sidebar.radio[0].set_value("Run History").run()

    assert not app.exception
    assert any(run_id in element.value for element in app.markdown)
    assert any("COMPLETED" in element.value for element in app.markdown)
    assert any(dataset_id in element.value for element in app.caption)
    transport.get.assert_called_with("/api/v1/runs")
    assert "run_ids" not in app.session_state.filtered_state


def test_run_history_filters_status_and_opens_selected_run() -> None:
    run_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
    transport = MagicMock(spec=httpx.Client)
    transport.get.return_value = _response(
        {
            "runs": [
                {
                    "run_id": run_id,
                    "dataset_id": "61d32f63-7c68-41df-814e-296fc47b5730",
                    "status": "RUNNING",
                    "qc_status": None,
                    "plan_revision": 3,
                    "attempt_id": None,
                    "index_updated_at": "2026-09-04T08:30:00+00:00",
                    "completed_at": None,
                    "evidence_status": "INDEX_ONLY",
                }
            ],
            "issues": [],
        }
    )

    with patch("httpx.Client", return_value=transport):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.sidebar.radio[0].set_value("Run History").run()
        app.selectbox[0].set_value("RUNNING").run()
        open_run = next(button for button in app.button if button.label == "Open run")
        open_run.click().run()

    assert not app.exception
    assert any(
        call.args == ("/api/v1/runs",)
        and call.kwargs == {"params": {"status": "RUNNING"}}
        for call in transport.get.call_args_list
    )
    assert app.session_state["run_id"] == run_id
    assert app.session_state["plan_revision"] == 3
    assert "runs" not in app.session_state.filtered_state
    assert "run_ids" not in app.session_state.filtered_state


def test_run_history_displays_manifest_integrity_issue() -> None:
    run_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
    transport = MagicMock(spec=httpx.Client)
    transport.get.return_value = _response(
        {
            "runs": [
                {
                    "run_id": run_id,
                    "dataset_id": "61d32f63-7c68-41df-814e-296fc47b5730",
                    "status": "COMPLETED",
                    "qc_status": "PASS",
                    "plan_revision": 1,
                    "attempt_id": "b99fb530-a935-45d8-8ccd-c5c01c07354d",
                    "index_updated_at": "2026-09-04T08:30:00+00:00",
                    "completed_at": None,
                    "evidence_status": "INVALID",
                }
            ],
            "issues": [
                {"run_id": run_id, "code": "RUN_MANIFEST_INVALID"},
            ],
        }
    )

    with patch("httpx.Client", return_value=transport):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.sidebar.radio[0].set_value("Run History").run()

    assert not app.exception
    assert any("Evidence: INVALID" in element.value for element in app.caption)
    assert any("RUN_MANIFEST_INVALID" in element.value for element in app.warning)


def test_sidebar_exposes_all_mvp_pages_with_mock_http_client() -> None:
    client = MagicMock(spec=httpx.Client)

    with patch("httpx.Client", return_value=client):
        app = AppTest.from_file(str(APP_PATH)).run()

    assert not app.exception
    assert tuple(app.sidebar.radio[0].options) == PAGES


def test_streamlit_app_does_not_import_workflow_or_execution() -> None:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert not any(
        module == "bioagent.workflow"
        or module.startswith("bioagent.workflow.")
        or module == "bioagent.execution"
        or module.startswith("bioagent.execution.")
        for module in imported_modules
    )
