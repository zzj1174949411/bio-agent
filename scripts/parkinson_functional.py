"""Offline Entrez annotation and human Reactome ORA for the one-off PD analysis."""

from __future__ import annotations

import csv
import gzip
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from scipy.stats import hypergeom


@dataclass(frozen=True)
class Pathway:
    name: str
    genes: frozenset[str]


COLUMNS = [
    "pathway_id",
    "name",
    "overlap_count",
    "pathway_background_count",
    "background_count",
    "hit_count",
    "expected_overlap",
    "fold_enrichment",
    "p_value",
    "q_value",
    "overlap_ids",
    "overlap_symbols",
]


def benjamini_hochberg(pvalues: Iterable[float]) -> list[float]:
    values = [float(p) for p in pvalues]
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in values):
        raise ValueError("INVALID_P_VALUE")
    order = sorted(range(len(values)), key=values.__getitem__)
    adjusted = [1.0] * len(values)
    previous = 1.0
    for rank in range(len(order), 0, -1):
        i = order[rank - 1]
        previous = min(previous, values[i] * len(order) / rank)
        adjusted[i] = previous
    return adjusted


def load_annotation(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, compression="infer")
    aliases = {
        "gene_id": ["GeneID", "gene_id", "#GeneID"],
        "symbol": ["Symbol", "symbol"],
        "name": ["Description", "description", "GeneName", "name"],
        "gene_type": ["GeneType", "Type", "type_of_gene", "gene_type"],
    }
    selected = {}
    for output, names in aliases.items():
        existing = next((name for name in names if name in frame.columns), None)
        if existing is None:
            if output in {"gene_id", "symbol"}:
                raise ValueError("ANNOTATION_COLUMNS_MISSING")
            selected[output] = pd.Series("", index=frame.index, dtype=str)
        else:
            selected[output] = frame[existing].replace("-", "")
    result = pd.DataFrame(selected)
    if result.gene_id.duplicated().any():
        raise ValueError("DUPLICATE_GENE_ID")
    if not result.gene_id.str.fullmatch(r"[1-9][0-9]*").all():
        raise ValueError("INVALID_ENTREZ_ID")
    return result


def annotate_results(frame: pd.DataFrame, annotation: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["feature_id"] = data["feature_id"].astype(str)
    return data.merge(
        annotation,
        how="left",
        left_on="feature_id",
        right_on="gene_id",
        sort=False,
        validate="many_to_one",
    )


def load_reactome(path: str | Path) -> dict[str, Pathway]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    names: dict[str, str] = {}
    members: dict[str, set[str]] = {}
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.reader(stream, delimiter="\t"):
            if not row:
                continue
            if len(row) != 6:
                raise ValueError("REACTOME_ROW_INVALID")
            gene, identity, _, name, _, species = row
            if species != "Homo sapiens":
                continue
            if not identity.startswith("R-HSA-") or not gene.isdigit():
                raise ValueError("REACTOME_HUMAN_ID_INVALID")
            if identity in names and names[identity] != name:
                raise ValueError("REACTOME_NAME_CONFLICT")
            names[identity] = name
            members.setdefault(identity, set()).add(gene)
    return {key: Pathway(names[key], frozenset(genes)) for key, genes in members.items()}


def overrepresentation(
    hits: Iterable[str],
    background: Iterable[str],
    pathways: Mapping[str, Pathway],
    symbols: Mapping[str, str] | None = None,
    min_size: int = 10,
    max_size: int = 500,
) -> tuple[pd.DataFrame, dict]:
    if min_size < 1 or max_size < min_size:
        raise ValueError("INVALID_PATHWAY_SIZE_RANGE")
    supplied_hits, supplied_background = set(map(str, hits)), set(map(str, background))
    if supplied_hits - supplied_background:
        raise ValueError("HITS_OUTSIDE_BACKGROUND")
    if any(not identity.startswith("R-HSA-") for identity in pathways):
        raise ValueError("HUMAN_REACTOME_PATHWAYS_REQUIRED")
    annotated = set().union(*(path.genes for path in pathways.values())) if pathways else set()
    universe = supplied_background & annotated
    query = supplied_hits & universe
    audit = {
        "background_input_count": len(supplied_background),
        "background_annotated_count": len(universe),
        "background_unannotated_ids": sorted(supplied_background - annotated),
        "hits_input_count": len(supplied_hits),
        "hits_annotated_count": len(query),
        "hits_unannotated_ids": sorted(supplied_hits - annotated),
        "min_size": min_size,
        "max_size": max_size,
        "multiple_testing": (
            "BH across all eligible pathways, including zero-overlap; "
            "one call is one testing family"
        ),
    }
    rows = []
    for identity, pathway in sorted(pathways.items()):
        tested_members = pathway.genes & universe
        if not min_size <= len(tested_members) <= max_size:
            continue
        overlap = sorted(query & tested_members, key=int)
        expected = len(query) * len(tested_members) / len(universe)
        rows.append(
            {
                "pathway_id": identity,
                "name": pathway.name,
                "overlap_count": len(overlap),
                "pathway_background_count": len(tested_members),
                "background_count": len(universe),
                "hit_count": len(query),
                "expected_overlap": expected,
                "fold_enrichment": len(overlap) / expected if expected else math.nan,
                "p_value": float(
                    hypergeom.sf(len(overlap) - 1, len(universe), len(tested_members), len(query))
                )
                if query
                else 1.0,
                "overlap_ids": ";".join(overlap),
                "overlap_symbols": ";".join((symbols or {}).get(gene, "") for gene in overlap),
            }
        )
    audit["tested_pathways"] = len(rows)
    table = pd.DataFrame(rows)
    if table.empty:
        return pd.DataFrame(columns=COLUMNS), audit
    table["q_value"] = benjamini_hochberg(table.p_value)
    return table[COLUMNS].sort_values(
        ["q_value", "p_value", "pathway_id"], kind="stable"
    ).reset_index(drop=True), audit
