from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bioagent.datasets.parser import ParsedDataset, load_dataset
from bioagent.datasets.validator import DatasetValidation, validate_dataset
from bioagent.domain.plans import Comparison
from bioagent.domain.qc import QCStatus

FIXTURES = Path("tests/fixtures")
COMPARISON = Comparison(factor="condition", numerator="A", denominator="B")


def _dataset(
    values: list[object],
    *,
    sample_ids: list[str] | None = None,
    conditions: list[object] | None = None,
) -> ParsedDataset:
    ids = sample_ids or ["A1", "A2", "B1", "B2"]
    groups = conditions or ["A", "A", "B", "B"]
    return ParsedDataset(
        counts=pd.DataFrame([values], index=pd.Index(["G1"], name="feature_id"), columns=ids),
        metadata=pd.DataFrame(
            {"condition": groups},
            index=pd.Index(ids, name="sample_id"),
        ),
    )


def _codes(validation: DatasetValidation) -> list[str]:
    return [issue.code for issue in validation.qc.issues]


def test_valid_dataset_warns_only_for_removed_zero_features() -> None:
    dataset = load_dataset(
        FIXTURES / "counts_valid.csv",
        FIXTURES / "metadata_valid.csv",
    )

    validation = validate_dataset(
        dataset,
        Comparison(factor="condition", numerator="AD", denominator="Control"),
    )

    assert validation.is_valid
    assert validation.qc.status is QCStatus.WARN
    assert _codes(validation) == ["ZERO_FEATURE_REMOVED"]
    assert validation.zero_feature_count == 1
    assert validation.counts.index.tolist() == ["GENE_1", "GENE_2"]


def test_validation_reorders_metadata_to_match_counts() -> None:
    dataset = _dataset([1, 2, 3, 4])
    dataset.metadata.sort_index(ascending=False, inplace=True)

    validation = validate_dataset(dataset, COMPARISON)

    assert validation.metadata.index.tolist() == dataset.counts.columns.tolist()
    event = next(issue for issue in validation.qc.issues if issue.code == "METADATA_REORDERED")
    assert event.status is QCStatus.PASS
    assert event.evidence == {
        "original_order": ["B2", "B1", "A2", "A1"],
        "counts_order": ["A1", "A2", "B1", "B2"],
    }


def test_validation_container_prevents_field_reassignment() -> None:
    validation = validate_dataset(_dataset([1, 2, 3, 4]), COMPARISON)

    with pytest.raises(FrozenInstanceError):
        validation.zero_feature_count = 99


def test_duplicate_feature_id_fails_with_stable_code() -> None:
    source = _dataset([1, 2, 3, 4])
    dataset = ParsedDataset(
        counts=pd.concat([source.counts, source.counts]),
        metadata=source.metadata,
    )

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "DUPLICATE_FEATURE_ID" in _codes(validation)


def test_duplicate_counts_sample_id_fails_with_stable_code() -> None:
    dataset = _dataset(
        [1, 2, 3, 4],
        sample_ids=["A1", "A1", "B1", "B2"],
        conditions=["A", "A", "B", "B"],
    )

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "DUPLICATE_SAMPLE_ID" in _codes(validation)


def test_duplicate_metadata_sample_id_fails_with_stable_code() -> None:
    dataset = _dataset([1, 2, 3, 4])
    dataset.metadata.index = pd.Index(["A1", "A1", "B1", "B2"], name="sample_id")

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "DUPLICATE_SAMPLE_ID" in _codes(validation)


@pytest.mark.parametrize(
    ("metadata", "duplicate_columns"),
    [
        (
            pd.DataFrame(
                [
                    ["A", "A"],
                    ["A", "A"],
                    ["B", "B"],
                    ["B", "B"],
                ],
                columns=["condition", "condition"],
                index=pd.Index(["A1", "A2", "B1", "B2"], name="sample_id"),
            ),
            ["condition"],
        ),
        (
            pd.DataFrame(
                [
                    ["A", "x", "x"],
                    ["A", "x", "x"],
                    ["B", "y", "y"],
                    ["B", "y", "y"],
                ],
                columns=["condition", "batch", "batch"],
                index=pd.Index(["A1", "A2", "B1", "B2"], name="sample_id"),
            ),
            ["batch"],
        ),
    ],
)
def test_duplicate_metadata_columns_fail_with_stable_code(
    metadata: pd.DataFrame,
    duplicate_columns: list[str],
) -> None:
    source = _dataset([1, 2, 3, 4])
    dataset = ParsedDataset(counts=source.counts, metadata=metadata)

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    issue = next(
        issue for issue in validation.qc.issues if issue.code == "DUPLICATE_METADATA_COLUMN"
    )
    assert issue.status is QCStatus.FAIL
    assert issue.evidence == {"duplicate_columns": duplicate_columns}


def test_negative_count_fails_with_stable_code() -> None:
    validation = validate_dataset(_dataset([1, -1, 3, 4]), COMPARISON)

    assert not validation.is_valid
    assert "NEGATIVE_COUNT" in _codes(validation)


@pytest.mark.parametrize("value", [2_147_483_648, 9_223_372_036_854_775_808])
def test_count_outside_r_integer_range_fails_with_stable_code(value: int) -> None:
    validation = validate_dataset(_dataset([value, 2, 3, 4]), COMPARISON)

    assert not validation.is_valid
    assert "COUNT_OUT_OF_RANGE" in _codes(validation)


@pytest.mark.parametrize("value", [1.5, "not-a-count"])
def test_non_integer_count_fails_with_stable_code(value: object) -> None:
    validation = validate_dataset(_dataset([value, 2, 3, 4]), COMPARISON)

    assert not validation.is_valid
    assert "NON_INTEGER_COUNT" in _codes(validation)


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_non_finite_count_fails_with_stable_code(value: float) -> None:
    validation = validate_dataset(_dataset([value, 2, 3, 4]), COMPARISON)

    assert not validation.is_valid
    assert "NON_FINITE_COUNT" in _codes(validation)


def test_sample_set_mismatch_fails_with_stable_code() -> None:
    dataset = _dataset([1, 2, 3, 4])
    dataset.metadata.index = pd.Index(["A1", "A2", "B1", "B3"], name="sample_id")

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "SAMPLE_SET_MISMATCH" in _codes(validation)


def test_missing_factor_fails_with_stable_code() -> None:
    dataset = _dataset([1, 2, 3, 4])
    dataset.metadata.rename(columns={"condition": "batch"}, inplace=True)

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "MISSING_FACTOR" in _codes(validation)


def test_missing_factor_value_fails_with_stable_code() -> None:
    dataset = _dataset([1, 2, 3, 4], conditions=["A", "A", "B", None])

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "MISSING_FACTOR_VALUE" in _codes(validation)


def test_factor_with_more_than_two_levels_fails_with_stable_code() -> None:
    dataset = _dataset([1, 2, 3, 4], conditions=["A", "A", "B", "C"])

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "INVALID_FACTOR_LEVEL_COUNT" in _codes(validation)


def test_unknown_comparison_level_fails_with_stable_code() -> None:
    comparison = Comparison(factor="condition", numerator="A", denominator="Control")

    validation = validate_dataset(_dataset([1, 2, 3, 4]), comparison)

    assert not validation.is_valid
    assert "INVALID_COMPARISON_LEVEL" in _codes(validation)


def test_group_with_fewer_than_two_replicates_fails() -> None:
    dataset = _dataset(
        [1, 2, 3],
        sample_ids=["A1", "B1", "B2"],
        conditions=["A", "B", "B"],
    )

    validation = validate_dataset(dataset, COMPARISON)

    assert not validation.is_valid
    assert "LOW_REPLICATE_NUMBER" in _codes(validation)


def test_groups_with_exactly_two_replicates_warn() -> None:
    validation = validate_dataset(_dataset([1, 2, 3, 4]), COMPARISON)

    assert validation.is_valid
    assert validation.qc.status is QCStatus.WARN
    assert _codes(validation) == ["LOW_REPLICATE_NUMBER"]


def test_zero_library_sample_fails_with_stable_code() -> None:
    validation = validate_dataset(_dataset([0, 2, 3, 4]), COMPARISON)

    assert not validation.is_valid
    assert "ZERO_LIBRARY_SIZE" in _codes(validation)
