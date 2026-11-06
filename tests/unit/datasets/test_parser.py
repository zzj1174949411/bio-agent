from pathlib import Path

import pytest

from bioagent.datasets.parser import load_dataset

FIXTURES = Path("tests/fixtures")


def test_load_dataset_uses_csv_suffix_and_sets_contract_indexes() -> None:
    dataset = load_dataset(
        FIXTURES / "counts_valid.csv",
        FIXTURES / "metadata_valid.csv",
    )

    assert dataset.counts.index.name == "feature_id"
    assert dataset.counts.index.tolist() == ["GENE_1", "GENE_2", "GENE_3"]
    assert dataset.counts.columns.tolist() == [
        "AD_1",
        "AD_2",
        "AD_3",
        "CTRL_1",
        "CTRL_2",
        "CTRL_3",
    ]
    assert dataset.metadata.index.name == "sample_id"
    assert dataset.metadata.index.tolist() == [
        "AD_1",
        "AD_2",
        "AD_3",
        "CTRL_1",
        "CTRL_2",
        "CTRL_3",
    ]


def test_load_dataset_uses_tsv_suffix(tmp_path: Path) -> None:
    counts_path = tmp_path / "counts.tsv"
    metadata_path = tmp_path / "metadata.tsv"
    counts_path.write_text("feature_id\tS1\tS2\nG1\t1\t2\n", encoding="utf-8")
    metadata_path.write_text(
        "sample_id\tcondition\nS1\tA\nS2\tB\n",
        encoding="utf-8",
    )

    dataset = load_dataset(counts_path, metadata_path)

    assert dataset.counts.loc["G1", "S2"] == 2
    assert dataset.metadata.loc["S2", "condition"] == "B"


def test_load_dataset_rejects_unsupported_suffix(tmp_path: Path) -> None:
    counts_path = tmp_path / "counts.txt"
    counts_path.write_text("feature_id,S1\nG1,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported dataset suffix"):
        load_dataset(counts_path, FIXTURES / "metadata_valid.csv")


def test_load_dataset_requires_feature_id_as_first_counts_column(tmp_path: Path) -> None:
    counts_path = tmp_path / "counts.csv"
    counts_path.write_text("gene,S1\nG1,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="counts first column must be feature_id"):
        load_dataset(counts_path, FIXTURES / "metadata_valid.csv")


def test_load_dataset_requires_metadata_sample_id(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.csv"
    metadata_path.write_text("sample,condition\nS1,A\n", encoding="utf-8")

    with pytest.raises(ValueError, match="metadata must contain sample_id"):
        load_dataset(FIXTURES / "counts_valid.csv", metadata_path)


def test_load_dataset_preserves_duplicate_sample_columns_for_validation(tmp_path: Path) -> None:
    counts_path = tmp_path / "counts.csv"
    metadata_path = tmp_path / "metadata.csv"
    counts_path.write_text("feature_id,S1,S1\nG1,1,2\n", encoding="utf-8")
    metadata_path.write_text("sample_id,condition\nS1,A\n", encoding="utf-8")

    dataset = load_dataset(counts_path, metadata_path)

    assert dataset.counts.columns.tolist() == ["S1", "S1"]


def test_load_dataset_preserves_identifier_and_metadata_text(tmp_path: Path) -> None:
    counts_path = tmp_path / "counts.csv"
    metadata_path = tmp_path / "metadata.csv"
    counts_path.write_text(
        "feature_id,001,002\n0001,1,2\n",
        encoding="utf-8",
    )
    metadata_path.write_text(
        "sample_id,condition\n001,01\n002,NA\n",
        encoding="utf-8",
    )

    dataset = load_dataset(counts_path, metadata_path)

    assert dataset.counts.index.tolist() == ["0001"]
    assert dataset.counts.columns.tolist() == ["001", "002"]
    assert dataset.metadata.index.tolist() == ["001", "002"]
    assert dataset.metadata["condition"].tolist() == ["01", "NA"]


@pytest.mark.parametrize("row", ["G1,1,2", "G1"])
def test_load_dataset_rejects_rows_with_wrong_field_count(tmp_path: Path, row: str) -> None:
    counts_path = tmp_path / "counts.csv"
    counts_path.write_text(f"feature_id,S1\n{row}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dataset row width does not match header"):
        load_dataset(counts_path, FIXTURES / "metadata_valid.csv")
