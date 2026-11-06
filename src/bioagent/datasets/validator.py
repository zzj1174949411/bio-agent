from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
from pydantic import JsonValue

from bioagent.datasets.parser import ParsedDataset
from bioagent.domain.plans import Comparison
from bioagent.domain.qc import QCIssue, QCReport, QCStatus

EvidenceValue = str | int | float | bool | None | list[str] | dict[str, int]
_MAX_R_INTEGER = int(np.iinfo(np.int32).max)


@dataclass(frozen=True)
class DatasetValidation:
    """Shallowly immutable validation snapshot containing mutable DataFrames.

    Execution boundaries must reload repository files, verify their hashes, and
    rerun deterministic validation instead of trusting a previously returned
    snapshot.
    """

    counts: pd.DataFrame
    metadata: pd.DataFrame
    qc: QCReport
    zero_feature_count: int

    @property
    def is_valid(self) -> bool:
        return self.qc.status is not QCStatus.FAIL


def _issue(
    code: str,
    status: QCStatus,
    message: str,
    **evidence: EvidenceValue,
) -> QCIssue:
    json_evidence = cast(dict[str, JsonValue], evidence)
    return QCIssue(code=code, status=status, message=message, evidence=json_evidence)


def _overall_status(issues: list[QCIssue]) -> QCStatus:
    if any(issue.status is QCStatus.FAIL for issue in issues):
        return QCStatus.FAIL
    if any(issue.status is QCStatus.WARN for issue in issues):
        return QCStatus.WARN
    return QCStatus.PASS


def validate_dataset(dataset: ParsedDataset, comparison: Comparison) -> DatasetValidation:
    counts = dataset.counts.copy()
    metadata = dataset.metadata.copy()
    issues: list[QCIssue] = []

    if counts.index.has_duplicates:
        duplicates = counts.index[counts.index.duplicated()].unique().astype(str).tolist()
        issues.append(
            _issue(
                "DUPLICATE_FEATURE_ID",
                QCStatus.FAIL,
                "feature_id values must be unique",
                duplicate_ids=duplicates,
            )
        )

    duplicate_sample_locations: list[str] = []
    if counts.columns.has_duplicates:
        duplicate_sample_locations.append("counts")
    if metadata.index.has_duplicates:
        duplicate_sample_locations.append("metadata")
    if duplicate_sample_locations:
        issues.append(
            _issue(
                "DUPLICATE_SAMPLE_ID",
                QCStatus.FAIL,
                "sample_id values must be unique",
                locations=duplicate_sample_locations,
            )
        )

    if metadata.columns.has_duplicates:
        duplicate_columns = (
            metadata.columns[metadata.columns.duplicated()]
            .unique()
            .astype(str)
            .tolist()
        )
        issues.append(
            _issue(
                "DUPLICATE_METADATA_COLUMN",
                QCStatus.FAIL,
                "metadata column names must be unique",
                duplicate_columns=duplicate_columns,
            )
        )

    if bool(pd.isna(counts.index).any()):
        issues.append(
            _issue(
                "MISSING_FEATURE_ID",
                QCStatus.FAIL,
                "feature_id values must not be missing",
            )
        )
    if bool(pd.isna(counts.columns).any()) or bool(pd.isna(metadata.index).any()):
        issues.append(
            _issue(
                "MISSING_SAMPLE_ID",
                QCStatus.FAIL,
                "sample_id values must not be missing",
            )
        )

    count_sample_ids = counts.columns.astype(str).tolist()
    metadata_sample_ids = metadata.index.astype(str).tolist()
    sample_sets_match = set(count_sample_ids) == set(metadata_sample_ids)
    if not sample_sets_match:
        issues.append(
            _issue(
                "SAMPLE_SET_MISMATCH",
                QCStatus.FAIL,
                "counts and metadata sample sets must match exactly",
                counts_only=sorted(set(count_sample_ids) - set(metadata_sample_ids)),
                metadata_only=sorted(set(metadata_sample_ids) - set(count_sample_ids)),
            )
        )
    elif not duplicate_sample_locations:
        if metadata_sample_ids != count_sample_ids:
            issues.append(
                _issue(
                    "METADATA_REORDERED",
                    QCStatus.PASS,
                    "metadata rows were reordered to match counts columns",
                    original_order=metadata_sample_ids,
                    counts_order=count_sample_ids,
                )
            )
        metadata.index = metadata.index.astype(str)
        counts.columns = counts.columns.astype(str)
        metadata = metadata.loc[counts.columns].copy()

    numeric_counts = counts.apply(pd.to_numeric, errors="coerce")
    original_missing = counts.isna()
    coercion_failed = numeric_counts.isna() & ~original_missing
    numeric_array = numeric_counts.to_numpy(dtype=float)
    finite_array = np.isfinite(numeric_array)
    non_finite = original_missing.to_numpy() | (~finite_array & ~coercion_failed.to_numpy())

    if bool(coercion_failed.to_numpy().any()):
        issues.append(
            _issue(
                "NON_INTEGER_COUNT",
                QCStatus.FAIL,
                "count values must be integers",
            )
        )
    if bool(non_finite.any()):
        issues.append(
            _issue(
                "NON_FINITE_COUNT",
                QCStatus.FAIL,
                "count values must be finite",
            )
        )

    fractional = finite_array & (numeric_array != np.floor(numeric_array))
    if bool(fractional.any()):
        issues.append(
            _issue(
                "NON_INTEGER_COUNT",
                QCStatus.FAIL,
                "count values must be integers",
            )
        )
    above_r_integer_range = numeric_counts.gt(_MAX_R_INTEGER).fillna(False).to_numpy()
    if bool(above_r_integer_range.any()):
        issues.append(
            _issue(
                "COUNT_OUT_OF_RANGE",
                QCStatus.FAIL,
                "count values must fit the R integer range",
                maximum=_MAX_R_INTEGER,
            )
        )
    if bool((finite_array & (numeric_array < 0)).any()):
        issues.append(
            _issue(
                "NEGATIVE_COUNT",
                QCStatus.FAIL,
                "count values must be non-negative",
            )
        )

    count_codes = {issue.code for issue in issues}
    counts_are_valid = not {
        "NON_INTEGER_COUNT",
        "NON_FINITE_COUNT",
        "COUNT_OUT_OF_RANGE",
        "NEGATIVE_COUNT",
    } & count_codes
    zero_feature_count = 0
    if counts_are_valid:
        counts = numeric_counts.astype("int64")
        zero_features = counts.sum(axis=1) == 0
        zero_feature_count = int(zero_features.sum())
        if zero_feature_count:
            counts = counts.loc[~zero_features].copy()
            issues.append(
                _issue(
                    "ZERO_FEATURE_REMOVED",
                    QCStatus.WARN,
                    "all-zero features were removed",
                    feature_count=zero_feature_count,
                )
            )

        zero_libraries = counts.columns[counts.sum(axis=0) == 0].astype(str).tolist()
        if zero_libraries:
            issues.append(
                _issue(
                    "ZERO_LIBRARY_SIZE",
                    QCStatus.FAIL,
                    "samples must have a non-zero library size",
                    sample_ids=zero_libraries,
                )
            )

    factor_column_count = int((metadata.columns == comparison.factor).sum())
    if factor_column_count == 0:
        issues.append(
            _issue(
                "MISSING_FACTOR",
                QCStatus.FAIL,
                "selected factor is not present in metadata",
                factor=comparison.factor,
            )
        )
    elif factor_column_count == 1:
        factor = metadata[comparison.factor]
        if bool(factor.isna().any()):
            issues.append(
                _issue(
                    "MISSING_FACTOR_VALUE",
                    QCStatus.FAIL,
                    "selected factor must not contain missing values",
                    factor=comparison.factor,
                )
            )

        levels = factor.dropna().astype(str).unique().tolist()
        if len(levels) != 2:
            issues.append(
                _issue(
                    "INVALID_FACTOR_LEVEL_COUNT",
                    QCStatus.FAIL,
                    "selected factor must contain exactly two levels",
                    factor=comparison.factor,
                    level_count=len(levels),
                    levels=sorted(levels),
                )
            )
        elif {comparison.numerator, comparison.denominator} != set(levels):
            issues.append(
                _issue(
                    "INVALID_COMPARISON_LEVEL",
                    QCStatus.FAIL,
                    "comparison levels must match the selected factor levels",
                    levels=sorted(levels),
                )
            )
        else:
            factor_as_text = factor.astype(str)
            replicate_counts = {
                level: int((factor_as_text == level).sum())
                for level in (comparison.numerator, comparison.denominator)
            }
            minimum_replicates = min(replicate_counts.values())
            if minimum_replicates < 2:
                issues.append(
                    _issue(
                        "LOW_REPLICATE_NUMBER",
                        QCStatus.FAIL,
                        "each comparison group must contain at least two samples",
                        replicate_counts=replicate_counts,
                    )
                )
            elif minimum_replicates == 2:
                issues.append(
                    _issue(
                        "LOW_REPLICATE_NUMBER",
                        QCStatus.WARN,
                        "a comparison group contains only two samples",
                        replicate_counts=replicate_counts,
                    )
                )

    qc = QCReport(status=_overall_status(issues), issues=tuple(issues))
    return DatasetValidation(
        counts=counts,
        metadata=metadata,
        qc=qc,
        zero_feature_count=zero_feature_count,
    )
