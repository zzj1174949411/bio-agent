import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_SEPARATORS = {".csv": ",", ".tsv": "\t"}


@dataclass(frozen=True)
class ParsedDataset:
    counts: pd.DataFrame
    metadata: pd.DataFrame


def _read_table(path: Path, *, preserve_all_text: bool) -> pd.DataFrame:
    try:
        separator = _SEPARATORS[path.suffix]
    except KeyError as error:
        raise ValueError("unsupported dataset suffix") from error

    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=separator)
        try:
            header = next(reader)
        except StopIteration as error:
            raise ValueError("dataset file must not be empty") from error
        for row in reader:
            if row and len(row) != len(header):
                raise ValueError("dataset row width does not match header")

    if preserve_all_text:
        frame = pd.read_csv(
            path,
            sep=separator,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        )
    else:
        frame = pd.read_csv(
            path,
            sep=separator,
            dtype={header[0]: str},
            keep_default_na=False,
            na_values=[""],
        )
    if len(frame.columns) != len(header):
        raise ValueError("dataset header does not match parsed columns")
    frame.columns = header
    return frame


def load_dataset(counts_path: Path, metadata_path: Path) -> ParsedDataset:
    counts = _read_table(counts_path, preserve_all_text=False)
    metadata = _read_table(metadata_path, preserve_all_text=True)

    if not counts.columns.empty and counts.columns[0] != "feature_id":
        raise ValueError("counts first column must be feature_id")
    if counts.columns.tolist().count("feature_id") != 1:
        raise ValueError("counts must contain exactly one feature_id column")
    if metadata.columns.tolist().count("sample_id") != 1:
        raise ValueError("metadata must contain sample_id")

    return ParsedDataset(
        counts=counts.set_index("feature_id"),
        metadata=metadata.set_index("sample_id"),
    )
