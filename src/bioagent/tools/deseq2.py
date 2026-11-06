import json
from collections.abc import Collection
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
from pydantic import JsonValue

from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCIssue, QCReport, QCStatus
from bioagent.tools.registry import ToolSpec

_RESULT_COLUMNS = (
    "feature_id",
    "baseMean",
    "log2FoldChange",
    "lfcSE",
    "stat",
    "pvalue",
    "padj",
)
_PCA_COLUMNS = ("PC1", "PC2", "sample_id", "factor_level")


def _relative_project_path(
    project_root: Path,
    path: Path,
    *,
    label: str,
    must_exist: bool,
) -> str:
    root = project_root.resolve()
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"{label} must be inside project root")
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(f"{label} not found")
    return resolved.relative_to(root).as_posix()


def write_deseq2_parameters(
    *,
    plan: AnalysisPlan,
    project_root: Path,
    counts_path: Path,
    metadata_path: Path,
    attempt_dir: Path,
) -> Path:
    root = project_root.resolve()
    counts_relative = _relative_project_path(
        root,
        counts_path,
        label="counts_path",
        must_exist=True,
    )
    metadata_relative = _relative_project_path(
        root,
        metadata_path,
        label="metadata_path",
        must_exist=True,
    )
    output_relative = _relative_project_path(
        root,
        attempt_dir,
        label="attempt_dir",
        must_exist=False,
    )
    resolved_attempt = root / output_relative
    if not resolved_attempt.is_dir():
        raise FileNotFoundError("attempt_dir not found")

    comparison = plan.comparison
    payload = {
        "counts_path": counts_relative,
        "metadata_path": metadata_relative,
        "output_dir": output_relative,
        "factor": comparison.factor,
        "numerator": comparison.numerator,
        "denominator": comparison.denominator,
        "alpha": plan.options.alpha,
        "lfc_shrink": plan.options.lfc_shrink,
    }
    parameter_path = resolved_attempt / "parameters.json"
    temporary_path = parameter_path.with_suffix(".json.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(parameter_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return parameter_path


def _issue(
    code: str,
    status: QCStatus,
    message: str,
    **evidence: JsonValue,
) -> QCIssue:
    return QCIssue(code=code, status=status, message=message, evidence=evidence)


def _status(issues: list[QCIssue]) -> QCStatus:
    if any(issue.status is QCStatus.FAIL for issue in issues):
        return QCStatus.FAIL
    if any(issue.status is QCStatus.WARN for issue in issues):
        return QCStatus.WARN
    return QCStatus.PASS


def _validate_result_table(
    path: Path,
    expected_feature_ids: tuple[str, ...],
    issues: list[QCIssue],
) -> pd.DataFrame | None:
    try:
        table = pd.read_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        issues.append(
            _issue(
                "INVALID_RESULT_TABLE",
                QCStatus.FAIL,
                "all_results.csv could not be parsed",
                error_type=type(error).__name__,
            )
        )
        return None
    if tuple(table.columns) != _RESULT_COLUMNS:
        issues.append(
            _issue(
                "INVALID_RESULT_COLUMNS",
                QCStatus.FAIL,
                "all_results.csv columns do not match the DESeq2 contract",
                columns=cast(JsonValue, table.columns.astype(str).tolist()),
            )
        )
        return None
    if len(table) != len(expected_feature_ids):
        issues.append(
            _issue(
                "RESULT_ROW_COUNT_MISMATCH",
                QCStatus.FAIL,
                "all_results.csv row count does not match validated input",
                expected=len(expected_feature_ids),
                observed=len(table),
            )
        )
    if table["feature_id"].isna().any() or table["feature_id"].duplicated().any():
        issues.append(
            _issue(
                "INVALID_RESULT_FEATURE_ID",
                QCStatus.FAIL,
                "result feature IDs must be present and unique",
            )
        )
    observed_feature_ids = set(table["feature_id"].dropna().astype(str))
    if observed_feature_ids != set(expected_feature_ids):
        issues.append(
            _issue(
                "RESULT_FEATURE_SET_MISMATCH",
                QCStatus.FAIL,
                "result feature IDs do not match the validated input",
                expected_count=len(expected_feature_ids),
                observed_count=len(observed_feature_ids),
            )
        )
    numeric_columns = list(_RESULT_COLUMNS[1:])
    numeric = table.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce")
    non_numeric_values = numeric.isna() & table.loc[:, numeric_columns].notna()
    numeric_values = numeric.to_numpy(dtype=float)
    invalid_values = (
        non_numeric_values.to_numpy().any()
        or not (np.isfinite(numeric_values) | np.isnan(numeric_values)).all()
        or (numeric["baseMean"].dropna() < 0).any()
        or (numeric["lfcSE"].dropna() < 0).any()
        or not numeric["pvalue"].dropna().between(0, 1).all()
        or not numeric["padj"].dropna().between(0, 1).all()
    )
    if invalid_values:
        issues.append(
            _issue(
                "INVALID_RESULT_VALUES",
                QCStatus.FAIL,
                "DESeq2 result statistics contain invalid numeric values",
            )
        )
    padj_proportion = float(numeric["padj"].isna().mean()) if len(table) else 0.0
    if padj_proportion > 0:
        issues.append(
            _issue(
                "NA_PADJ_VALUES",
                QCStatus.WARN,
                "DESeq2 independent filtering produced NA adjusted p-values",
                proportion=padj_proportion,
            )
        )
    return table


def _validate_significant_results(
    path: Path,
    all_results: pd.DataFrame | None,
    alpha: float,
    issues: list[QCIssue],
) -> None:
    try:
        table = pd.read_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        issues.append(
            _issue(
                "INVALID_SIGNIFICANT_RESULT_TABLE",
                QCStatus.FAIL,
                "significant_results.csv could not be parsed",
                error_type=type(error).__name__,
            )
        )
        return
    if tuple(table.columns) != _RESULT_COLUMNS:
        issues.append(
            _issue(
                "INVALID_SIGNIFICANT_RESULT_COLUMNS",
                QCStatus.FAIL,
                "significant_results.csv columns do not match the result contract",
                columns=cast(JsonValue, table.columns.astype(str).tolist()),
            )
        )
        return
    significant_ids = table["feature_id"].dropna().astype(str)
    numeric = table.loc[:, list(_RESULT_COLUMNS[1:])].apply(
        pd.to_numeric,
        errors="coerce",
    )
    non_numeric_values = numeric.isna() & table.loc[:, list(_RESULT_COLUMNS[1:])].notna()
    valid_padj = numeric["padj"].notna() & numeric["padj"].between(0, alpha)
    expected_ids: set[str] | None = None
    if all_results is not None:
        all_padj = pd.to_numeric(all_results["padj"], errors="coerce")
        expected_ids = set(
            all_results.loc[all_padj.notna() & all_padj.le(alpha), "feature_id"].astype(str)
        )
    if (
        table["feature_id"].isna().any()
        or significant_ids.duplicated().any()
        or non_numeric_values.to_numpy().any()
        or not valid_padj.all()
        or (expected_ids is not None and set(significant_ids) != expected_ids)
    ):
        issues.append(
            _issue(
                "INVALID_SIGNIFICANT_RESULTS",
                QCStatus.FAIL,
                "significant results must match adjusted p-values at the approved alpha",
                alpha=alpha,
            )
        )


def _validate_normalized_counts(
    path: Path,
    expected_feature_ids: tuple[str, ...],
    expected_sample_ids: tuple[str, ...],
    issues: list[QCIssue],
) -> None:
    try:
        table = pd.read_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        issues.append(
            _issue(
                "INVALID_NORMALIZED_COUNTS",
                QCStatus.FAIL,
                "normalized_counts.csv could not be parsed",
                error_type=type(error).__name__,
            )
        )
        return
    valid_columns = (
        len(table.columns) == len(expected_sample_ids) + 1
        and len(table.columns) > 0
        and table.columns[0] == "feature_id"
        and not table.columns.duplicated().any()
    )
    if not valid_columns:
        issues.append(
            _issue(
                "INVALID_NORMALIZED_COUNT_COLUMNS",
                QCStatus.FAIL,
                "normalized_counts.csv columns do not match the input samples",
                columns=cast(JsonValue, table.columns.astype(str).tolist()),
            )
        )
        return
    observed_sample_ids = tuple(str(column) for column in table.columns[1:])
    if set(observed_sample_ids) != set(expected_sample_ids):
        issues.append(
            _issue(
                "SAMPLE_SET_MISMATCH",
                QCStatus.FAIL,
                "normalized count sample IDs do not match validated input",
            )
        )
    observed_feature_ids = set(table["feature_id"].dropna().astype(str))
    if observed_feature_ids != set(expected_feature_ids):
        issues.append(
            _issue(
                "NORMALIZED_FEATURE_SET_MISMATCH",
                QCStatus.FAIL,
                "normalized count feature IDs do not match validated input",
            )
        )
    values = table.iloc[:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy()
    if (
        len(table) != len(expected_feature_ids)
        or table["feature_id"].isna().any()
        or table["feature_id"].duplicated().any()
        or not np.isfinite(values).all()
        or (values < 0).any()
    ):
        issues.append(
            _issue(
                "INVALID_NORMALIZED_COUNTS",
                QCStatus.FAIL,
                "normalized counts must be finite, non-negative, and match input rows",
                expected_features=len(expected_feature_ids),
                observed_rows=len(table),
            )
        )


def _validate_size_factors(
    path: Path,
    expected_sample_ids: tuple[str, ...],
    issues: list[QCIssue],
) -> None:
    try:
        table = pd.read_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        issues.append(
            _issue(
                "INVALID_SIZE_FACTORS",
                QCStatus.FAIL,
                "size_factors.csv could not be parsed",
                error_type=type(error).__name__,
            )
        )
        return
    if tuple(table.columns) != ("sample_id", "size_factor"):
        issues.append(
            _issue(
                "INVALID_SIZE_FACTOR_COLUMNS",
                QCStatus.FAIL,
                "size_factors.csv columns do not match the DESeq2 contract",
                columns=cast(JsonValue, table.columns.astype(str).tolist()),
            )
        )
        return
    factors = pd.to_numeric(table["size_factor"], errors="coerce").to_numpy()
    observed_sample_ids = set(table["sample_id"].dropna().astype(str))
    if observed_sample_ids != set(expected_sample_ids):
        issues.append(
            _issue(
                "SAMPLE_SET_MISMATCH",
                QCStatus.FAIL,
                "size factor sample IDs do not match validated input",
            )
        )
    if (
        len(table) != len(expected_sample_ids)
        or table["sample_id"].isna().any()
        or table["sample_id"].duplicated().any()
        or not np.isfinite(factors).all()
        or (factors <= 0).any()
    ):
        issues.append(
            _issue(
                "INVALID_SIZE_FACTORS",
                QCStatus.FAIL,
                "size factors must be finite, positive, and present for every sample",
                expected_samples=len(expected_sample_ids),
                observed_rows=len(table),
            )
        )


def _validate_pca(
    path: Path,
    expected_sample_ids: tuple[str, ...],
    issues: list[QCIssue],
) -> None:
    try:
        pca = pd.read_csv(path)
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        issues.append(
            _issue(
                "INVALID_PCA_COORDINATES",
                QCStatus.FAIL,
                "pca.csv could not be parsed",
                error_type=type(error).__name__,
            )
        )
        return
    valid_columns = tuple(pca.columns) == _PCA_COLUMNS
    coordinates_are_finite = False
    if valid_columns:
        coordinates = pca.loc[:, ["PC1", "PC2"]].apply(pd.to_numeric, errors="coerce")
        coordinates_are_finite = bool(np.isfinite(coordinates.to_numpy()).all())
    valid_sample_ids = (
        "sample_id" in pca
        and not pca["sample_id"].isna().any()
        and not pca["sample_id"].duplicated().any()
    )
    valid_factor_levels = "factor_level" in pca and not pca["factor_level"].isna().any()
    sample_set_matches = (
        "sample_id" in pca
        and set(pca["sample_id"].dropna().astype(str)) == set(expected_sample_ids)
    )
    if valid_sample_ids and not sample_set_matches:
        issues.append(
            _issue(
                "SAMPLE_SET_MISMATCH",
                QCStatus.FAIL,
                "PCA sample IDs do not match validated input",
            )
        )
    if (
        not valid_columns
        or len(pca) != len(expected_sample_ids)
        or not valid_sample_ids
        or not valid_factor_levels
        or not coordinates_are_finite
    ):
        issues.append(
            _issue(
                "INVALID_PCA_COORDINATES",
                QCStatus.FAIL,
                "pca.csv must contain finite PC1/PC2 coordinates for every sample",
                expected_samples=len(expected_sample_ids),
                observed_rows=len(pca),
            )
        )


def _validate_summary(
    path: Path,
    expected_feature_count: int,
    expected_sample_count: int,
    issues: list[QCIssue],
) -> None:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        issues.append(
            _issue(
                "INVALID_EXECUTION_SUMMARY",
                QCStatus.FAIL,
                "execution_summary.json could not be parsed",
                error_type=type(error).__name__,
            )
        )
        return
    if not isinstance(payload, dict) or (
        payload.get("status") != "success"
        or payload.get("n_features") != expected_feature_count
        or payload.get("n_samples") != expected_sample_count
    ):
        issues.append(
            _issue(
                "INVALID_EXECUTION_SUMMARY",
                QCStatus.FAIL,
                "execution summary does not match the successful run contract",
            )
        )


def validate_deseq2_outputs(
    *,
    spec: ToolSpec,
    attempt_dir: Path,
    expected_feature_ids: Collection[str],
    expected_sample_ids: Collection[str],
    alpha: float,
) -> QCReport:
    feature_ids = tuple(expected_feature_ids)
    sample_ids = tuple(expected_sample_ids)
    if (
        not feature_ids
        or not sample_ids
        or len(set(feature_ids)) != len(feature_ids)
        or len(set(sample_ids)) != len(sample_ids)
    ):
        raise ValueError("expected feature and sample IDs must be non-empty and unique")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    output_root = attempt_dir.resolve()
    issues: list[QCIssue] = []
    missing: set[str] = set()
    for artifact in spec.required_artifacts:
        path = spec.resolve_artifact(output_root, artifact)
        if not path.is_file():
            missing.add(artifact)
            issues.append(
                _issue(
                    "MISSING_REQUIRED_ARTIFACT",
                    QCStatus.FAIL,
                    "required DESeq2 artifact is missing",
                    relative_path=artifact,
                )
            )

    result_relative = "results/all_results.csv"
    all_results: pd.DataFrame | None = None
    if result_relative not in missing:
        all_results = _validate_result_table(
            spec.resolve_artifact(output_root, result_relative),
            feature_ids,
            issues,
        )
    significant_relative = "results/significant_results.csv"
    if significant_relative not in missing:
        _validate_significant_results(
            spec.resolve_artifact(output_root, significant_relative),
            all_results,
            alpha,
            issues,
        )
    normalized_relative = "results/normalized_counts.csv"
    if normalized_relative not in missing:
        _validate_normalized_counts(
            spec.resolve_artifact(output_root, normalized_relative),
            feature_ids,
            sample_ids,
            issues,
        )
    pca_relative = "results/pca.csv"
    if pca_relative not in missing:
        _validate_pca(
            spec.resolve_artifact(output_root, pca_relative),
            sample_ids,
            issues,
        )
    size_factors_relative = "results/size_factors.csv"
    if size_factors_relative not in missing:
        _validate_size_factors(
            spec.resolve_artifact(output_root, size_factors_relative),
            sample_ids,
            issues,
        )
    summary_relative = "results/execution_summary.json"
    if summary_relative not in missing:
        _validate_summary(
            spec.resolve_artifact(output_root, summary_relative),
            len(feature_ids),
            len(sample_ids),
            issues,
        )
    return QCReport(status=_status(issues), issues=tuple(issues))
