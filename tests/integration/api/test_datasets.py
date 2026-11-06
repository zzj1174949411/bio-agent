from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from bioagent.config import Settings
from bioagent.domain.plans import AnalysisPlan
from bioagent.llm.planner import PlanningDatasetSummary


class _Planner:
    def plan(
        self,
        *,
        user_goal: str,
        summary: PlanningDatasetSummary,
    ) -> AnalysisPlan:
        return AnalysisPlan(
            dataset_id=summary.dataset_id,
            comparison={
                "factor": "condition",
                "numerator": "AD",
                "denominator": "Control",
            },
        )


def _client(
    tmp_path: Path,
    *,
    max_upload_bytes: int = 10 * 1024 * 1024,
    max_request_bytes: int | None = None,
    max_rows: int = 100_000,
    max_columns: int = 10_000,
    parse_timeout_seconds: float = 10.0,
) -> TestClient:
    from bioagent.api.app import create_app

    settings = Settings(
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "checkpoints.sqlite",
    )
    overrides: dict[str, object] = {
        "planner": _Planner(),
        "executor": object(),
        "max_upload_bytes": max_upload_bytes,
        "max_rows": max_rows,
        "max_columns": max_columns,
        "parse_timeout_seconds": parse_timeout_seconds,
    }
    if max_request_bytes is not None:
        overrides["max_request_bytes"] = max_request_bytes
    return TestClient(create_app(settings, overrides=overrides))


def test_valid_dataset_upload_returns_id_and_validation(tmp_path: Path) -> None:
    fixtures = Path("tests/fixtures")

    with (
        _client(tmp_path) as client,
        (fixtures / "counts_valid.csv").open("rb") as counts,
        (fixtures / "metadata_valid.csv").open("rb") as metadata,
    ):
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", counts, "text/csv"),
                "metadata": ("metadata.csv", metadata, "text/csv"),
            },
        )

        assert response.status_code == 201
        dataset_id = response.json()["dataset_id"]
        assert str(UUID(dataset_id)) == dataset_id

        validation = client.get(f"/api/v1/datasets/{dataset_id}/validation")

    assert validation.status_code == 200
    payload = validation.json()
    assert payload["dataset_id"] == dataset_id
    assert payload["is_valid"] is True
    assert payload["summary"] == {
        "dataset_id": dataset_id,
        "feature_count": 2,
        "sample_count": 6,
        "categorical_levels": {"condition": ["AD", "Control"]},
    }
    assert payload["qc"]["status"] == "WARN"


def test_sample_mismatch_returns_422_with_stable_error_code(tmp_path: Path) -> None:
    counts = b"feature_id,S1,S2\nGENE_1,1,2\n"
    metadata = b"sample_id,condition\nS1,AD\nS3,Control\n"

    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", counts, "text/csv"),
                "metadata": ("metadata.csv", metadata, "text/csv"),
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SAMPLE_SET_MISMATCH"


def test_upload_rejects_unsupported_file_suffix(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.txt", b"feature_id,S1\nG1,1\n", "text/plain"),
                "metadata": (
                    "metadata.csv",
                    b"sample_id,condition\nS1,AD\n",
                    "text/csv",
                ),
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_discovers_binary_factor_after_extra_metadata(tmp_path: Path) -> None:
    counts = b"feature_id,S1,S2,S3,S4\nG1,1,2,3,4\n"
    metadata = (
        b"sample_id,subject_code,condition\n"
        b"S1,P1,AD\nS2,P2,AD\nS3,P3,Control\nS4,P4,Control\n"
    )

    with _client(tmp_path) as client:
        uploaded = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", counts, "text/csv"),
                "metadata": ("metadata.csv", metadata, "text/csv"),
            },
        )
        assert uploaded.status_code == 201
        validation = client.get(
            f"/api/v1/datasets/{uploaded.json()['dataset_id']}/validation"
        )

    assert validation.status_code == 200
    assert validation.json()["summary"]["categorical_levels"] == {
        "condition": ["AD", "Control"]
    }


def test_upload_enforces_configured_byte_limit(tmp_path: Path) -> None:
    with _client(tmp_path, max_upload_bytes=8) as client:
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", b"feature_id,S1\nG1,1\n", "text/csv"),
                "metadata": (
                    "metadata.csv",
                    b"sample_id,condition\nS1,AD\n",
                    "text/csv",
                ),
            },
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"


def test_upload_rejects_oversized_request_before_dataset_parsing(tmp_path: Path) -> None:
    with _client(tmp_path, max_request_bytes=64) as client:
        response = client.post(
            "/api/v1/datasets",
            headers={"content-length": "65"},
            files={
                "counts": ("counts.csv", b"x", "text/csv"),
                "metadata": ("metadata.csv", b"y", "text/csv"),
            },
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"


def test_upload_rejects_row_limit_before_pandas_parsing(tmp_path: Path) -> None:
    counts = b"feature_id,S1,S2\nG1,1,2\nG2,3,4\nG3,5,6\n"
    metadata = b"sample_id,condition\nS1,AD\nS2,Control\n"

    with _client(tmp_path, max_rows=2) as client:
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", counts, "text/csv"),
                "metadata": ("metadata.csv", metadata, "text/csv"),
            },
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "DATASET_LIMIT_EXCEEDED"


def test_upload_rejects_column_limit_before_pandas_parsing(tmp_path: Path) -> None:
    counts = b"feature_id,S1,S2\nG1,1,2\n"
    metadata = b"sample_id,condition\nS1,AD\nS2,Control\n"

    with _client(tmp_path, max_columns=2) as client:
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", counts, "text/csv"),
                "metadata": ("metadata.csv", metadata, "text/csv"),
            },
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "DATASET_LIMIT_EXCEEDED"


def test_upload_times_out_complete_parse_and_validation(tmp_path: Path) -> None:
    fixtures = Path("tests/fixtures")

    with (
        _client(tmp_path, parse_timeout_seconds=0.001) as client,
        (fixtures / "counts_valid.csv").open("rb") as counts,
        (fixtures / "metadata_valid.csv").open("rb") as metadata,
    ):
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", counts, "text/csv"),
                "metadata": ("metadata.csv", metadata, "text/csv"),
            },
        )

    assert response.status_code == 408
    assert response.json()["detail"]["code"] == "DATASET_PARSE_TIMEOUT"
