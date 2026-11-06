import json
import shutil
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from bioagent.domain.plans import AnalysisPlan, Comparison
from bioagent.domain.qc import QCStatus
from bioagent.execution.r_runner import RRunner
from bioagent.tools.deseq2 import validate_deseq2_outputs, write_deseq2_parameters
from bioagent.tools.registry import ToolRegistry, ToolSpec

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FEATURE_IDS = ("G1", "G2")
SAMPLE_IDS = ("S1", "S2")
ALPHA = 0.05


def _plan(*, lfc_shrink: bool = False) -> AnalysisPlan:
    return AnalysisPlan(
        dataset_id="b8b439c9-c576-4f87-ae41-69e0810c38c9",
        comparison=Comparison(
            factor="condition",
            numerator="AD",
            denominator="Control",
        ),
        options={"alpha": 0.05, "lfc_shrink": lfc_shrink, "random_seed": 42},
    )


def _write_valid_outputs(attempt_dir: Path) -> ToolSpec:
    spec = ToolRegistry(project_root=PROJECT_ROOT).get("deseq2")
    for artifact in spec.required_artifacts:
        path = attempt_dir / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    all_results = pd.DataFrame(
        {
            "feature_id": FEATURE_IDS,
            "baseMean": [10.0, 20.0],
            "log2FoldChange": [1.0, -1.0],
            "lfcSE": [0.1, 0.2],
            "stat": [10.0, -5.0],
            "pvalue": [0.001, 0.2],
            "padj": [0.002, 0.4],
        }
    )
    all_results.to_csv(attempt_dir / "results" / "all_results.csv", index=False)
    all_results.iloc[[0]].to_csv(
        attempt_dir / "results" / "significant_results.csv",
        index=False,
    )
    pd.DataFrame(
        {"feature_id": ["G1", "G2"], "S1": [10.0, 20.0], "S2": [12.0, 18.0]}
    ).to_csv(attempt_dir / "results" / "normalized_counts.csv", index=False)
    pd.DataFrame(
        {
            "PC1": [1.0, -1.0],
            "PC2": [0.5, -0.5],
            "sample_id": ["S1", "S2"],
            "factor_level": ["Control", "AD"],
        }
    ).to_csv(attempt_dir / "results" / "pca.csv", index=False)
    pd.DataFrame(
        {"sample_id": ["S1", "S2"], "size_factor": [0.9, 1.1]}
    ).to_csv(attempt_dir / "results" / "size_factors.csv", index=False)
    (attempt_dir / "results" / "execution_summary.json").write_text(
        json.dumps({"status": "success", "n_features": 2, "n_samples": 2}),
        encoding="utf-8",
    )
    return spec


def _validate_outputs(spec: ToolSpec, attempt_dir: Path):  # type: ignore[no-untyped-def]
    return validate_deseq2_outputs(
        spec=spec,
        attempt_dir=attempt_dir,
        expected_feature_ids=FEATURE_IDS,
        expected_sample_ids=SAMPLE_IDS,
        alpha=ALPHA,
    )


def test_parameter_adapter_writes_only_controlled_relative_paths(tmp_path: Path) -> None:
    project_root = tmp_path.resolve()
    counts_path = project_root / "data" / "dataset" / "counts.csv"
    metadata_path = project_root / "data" / "dataset" / "metadata.csv"
    attempt_dir = project_root / "runs" / "run" / "attempts" / "attempt"
    counts_path.parent.mkdir(parents=True)
    counts_path.write_text("feature_id,S1\nG1,1\n", encoding="utf-8")
    metadata_path.write_text("sample_id,condition\nS1,AD\n", encoding="utf-8")
    attempt_dir.mkdir(parents=True)

    parameter_path = write_deseq2_parameters(
        plan=_plan(),
        project_root=project_root,
        counts_path=counts_path,
        metadata_path=metadata_path,
        attempt_dir=attempt_dir,
    )

    assert parameter_path == attempt_dir / "parameters.json"
    assert json.loads(parameter_path.read_text(encoding="utf-8")) == {
        "alpha": 0.05,
        "counts_path": "data/dataset/counts.csv",
        "denominator": "Control",
        "factor": "condition",
        "lfc_shrink": False,
        "metadata_path": "data/dataset/metadata.csv",
        "numerator": "AD",
        "output_dir": "runs/run/attempts/attempt",
    }


def test_parameter_adapter_rejects_input_outside_project(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    attempt_dir = project_root / "runs" / "attempt"
    attempt_dir.mkdir(parents=True)
    metadata = project_root / "metadata.csv"
    metadata.write_text("sample_id,condition\nS1,AD\n", encoding="utf-8")
    outside_counts = tmp_path / "counts.csv"
    outside_counts.write_text("feature_id,S1\nG1,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="counts_path must be inside project root"):
        write_deseq2_parameters(
            plan=_plan(),
            project_root=project_root,
            counts_path=outside_counts,
            metadata_path=metadata,
            attempt_dir=attempt_dir,
        )


def test_output_validation_passes_complete_valid_outputs(tmp_path: Path) -> None:
    spec = _write_valid_outputs(tmp_path)

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.PASS
    assert report.issues == ()


def test_output_validation_warns_for_na_padj(tmp_path: Path) -> None:
    spec = _write_valid_outputs(tmp_path)
    results_path = tmp_path / "results" / "all_results.csv"
    results = pd.read_csv(results_path)
    results.loc[0, "padj"] = None
    results.to_csv(results_path, index=False)
    results.iloc[0:0].to_csv(
        tmp_path / "results" / "significant_results.csv",
        index=False,
    )

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.WARN
    assert report.issues[0].code == "NA_PADJ_VALUES"
    assert report.issues[0].evidence["proportion"] == 0.5


def test_output_validation_fails_for_missing_required_artifact(tmp_path: Path) -> None:
    spec = _write_valid_outputs(tmp_path)
    (tmp_path / "figures" / "volcano_plot.pdf").unlink()

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.FAIL
    assert report.issues[0].code == "MISSING_REQUIRED_ARTIFACT"
    assert report.issues[0].evidence["relative_path"] == "figures/volcano_plot.pdf"


@pytest.mark.parametrize(
    ("relative_path", "content", "expected_code"),
    [
        (
            "results/significant_results.csv",
            "feature_id,padj\nG1,0.01\n",
            "INVALID_SIGNIFICANT_RESULT_COLUMNS",
        ),
        (
            "results/normalized_counts.csv",
            "gene,S1,S2\nG1,10,12\nG2,20,18\n",
            "INVALID_NORMALIZED_COUNT_COLUMNS",
        ),
        (
            "results/size_factors.csv",
            "sample_id,factor\nS1,1\nS2,1\n",
            "INVALID_SIZE_FACTOR_COLUMNS",
        ),
    ],
)
def test_output_validation_rejects_invalid_csv_contracts(
    tmp_path: Path,
    relative_path: str,
    content: str,
    expected_code: str,
) -> None:
    spec = _write_valid_outputs(tmp_path)
    (tmp_path / relative_path).write_text(content, encoding="utf-8")

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.FAIL
    assert expected_code in {issue.code for issue in report.issues}


def test_output_validation_rejects_non_numeric_result_value(tmp_path: Path) -> None:
    spec = _write_valid_outputs(tmp_path)
    results_path = tmp_path / "results" / "all_results.csv"
    results = pd.read_csv(results_path)
    results["pvalue"] = results["pvalue"].astype(object)
    results.loc[0, "pvalue"] = "not-a-number"
    results.to_csv(results_path, index=False)

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.FAIL
    assert "INVALID_RESULT_VALUES" in {issue.code for issue in report.issues}


def test_output_validation_rejects_missing_pca_factor_level(tmp_path: Path) -> None:
    spec = _write_valid_outputs(tmp_path)
    pca_path = tmp_path / "results" / "pca.csv"
    pca = pd.read_csv(pca_path)
    pca.loc[0, "factor_level"] = None
    pca.to_csv(pca_path, index=False)

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.FAIL
    assert "INVALID_PCA_COORDINATES" in {issue.code for issue in report.issues}


@pytest.mark.parametrize(
    ("relative_path", "old_value", "new_value", "expected_code"),
    [
        ("results/all_results.csv", "G1", "OTHER_GENE", "RESULT_FEATURE_SET_MISMATCH"),
        (
            "results/normalized_counts.csv",
            "G1",
            "OTHER_GENE",
            "NORMALIZED_FEATURE_SET_MISMATCH",
        ),
        ("results/normalized_counts.csv", "S1", "OTHER_SAMPLE", "SAMPLE_SET_MISMATCH"),
        ("results/pca.csv", "S1", "OTHER_SAMPLE", "SAMPLE_SET_MISMATCH"),
        ("results/size_factors.csv", "S1", "OTHER_SAMPLE", "SAMPLE_SET_MISMATCH"),
    ],
)
def test_output_validation_rejects_foreign_feature_or_sample_ids(
    tmp_path: Path,
    relative_path: str,
    old_value: str,
    new_value: str,
    expected_code: str,
) -> None:
    spec = _write_valid_outputs(tmp_path)
    path = tmp_path / relative_path
    path.write_text(
        path.read_text(encoding="utf-8").replace(old_value, new_value),
        encoding="utf-8",
    )

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.FAIL
    assert expected_code in {issue.code for issue in report.issues}


def test_output_validation_rejects_corrupt_significant_results(tmp_path: Path) -> None:
    spec = _write_valid_outputs(tmp_path)
    significant_path = tmp_path / "results" / "significant_results.csv"
    significant = pd.read_csv(significant_path)
    significant.loc[0, "feature_id"] = "OTHER_GENE"
    significant.loc[0, "padj"] = 2.0
    significant.to_csv(significant_path, index=False)

    report = _validate_outputs(spec, tmp_path)

    assert report.status is QCStatus.FAIL
    assert "INVALID_SIGNIFICANT_RESULTS" in {issue.code for issue in report.issues}


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is not installed")
def test_real_deseq2_runner_preserves_ad_vs_control_direction() -> None:
    spec = ToolRegistry(project_root=PROJECT_ROOT).get("deseq2")
    attempt_dir = PROJECT_ROOT / "runs" / f"task6-integration-{uuid4()}"
    attempt_dir.mkdir(parents=True)
    try:
        parameters = write_deseq2_parameters(
            plan=_plan(lfc_shrink=False),
            project_root=PROJECT_ROOT,
            counts_path=PROJECT_ROOT / "tests" / "fixtures" / "counts_deseq2.csv",
            metadata_path=PROJECT_ROOT / "tests" / "fixtures" / "metadata_deseq2.csv",
            attempt_dir=attempt_dir,
        )
        extra_env: dict[str, str] = {}
        renv_library = (
            PROJECT_ROOT / "renv" / "library" / "windows" / "R-4.5" / "x86_64-w64-mingw32"
        )
        if renv_library.is_dir():
            extra_env["R_LIBS"] = str(renv_library)
            extra_env["RENV_CONFIG_AUTOLOADER_ENABLED"] = "FALSE"
        runner = RRunner(
            project_root=PROJECT_ROOT,
            rscript="Rscript",
            extra_env=extra_env,
        )

        result = runner.run(spec=spec, attempt_dir=attempt_dir, parameters=parameters)
        report = validate_deseq2_outputs(
            spec=spec,
            attempt_dir=attempt_dir,
            expected_feature_ids=tuple(f"GENE_{index:03d}" for index in range(1, 201)),
            expected_sample_ids=(
                "Control_1",
                "Control_2",
                "Control_3",
                "AD_1",
                "AD_2",
                "AD_3",
            ),
            alpha=0.05,
        )
        table = pd.read_csv(attempt_dir / "results" / "all_results.csv")
        target = table.loc[table["feature_id"] == "GENE_001"].iloc[0]

        assert result.returncode == 0
        assert report.status in {QCStatus.PASS, QCStatus.WARN}
        assert target["log2FoldChange"] > 0
    finally:
        shutil.rmtree(attempt_dir, ignore_errors=True)
