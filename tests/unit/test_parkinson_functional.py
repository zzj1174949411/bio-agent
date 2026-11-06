import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from parkinson_functional import (
    Pathway,
    benjamini_hochberg,
    load_annotation,
    load_reactome,
    overrepresentation,
)


def test_manual_bh():
    assert benjamini_hochberg([0.04, 0.01, 1]) == pytest.approx([0.06, 0.03, 1])


def test_hypergeom_zero_overlap_is_bh_hypothesis():
    paths = {
        "R-HSA-1": Pathway("one", frozenset({"1", "2"})),
        "R-HSA-2": Pathway("two", frozenset({"4", "5"})),
        "R-HSA-3": Pathway("too small", frozenset({"3"})),
    }
    table, audit = overrepresentation({"1", "2"}, {"1", "2", "3", "4", "5"}, paths, min_size=2)
    row = table.set_index("pathway_id").loc["R-HSA-1"]
    assert row.p_value == pytest.approx(0.1)
    assert row.q_value == pytest.approx(0.2)
    assert row.fold_enrichment == pytest.approx(2.5)
    assert audit["tested_pathways"] == 2
    assert table.set_index("pathway_id").loc["R-HSA-2", "p_value"] == 1


def test_mapping_losses_and_outside_hits_are_not_hidden():
    paths = {"R-HSA-1": Pathway("one", frozenset({"1", "2"}))}
    table, audit = overrepresentation({"1", "9"}, {"1", "2", "9"}, paths, min_size=1)
    assert audit["hits_unannotated_ids"] == ["9"]
    assert audit["background_unannotated_ids"] == ["9"]
    assert table.iloc[0].background_count == 2
    with pytest.raises(ValueError, match="HITS_OUTSIDE_BACKGROUND"):
        overrepresentation({"3"}, {"1", "2"}, paths, min_size=1)


def test_duplicate_symbols_preserve_entrez_rows(tmp_path):
    p = tmp_path / "a.tsv"
    p.write_text(
        "GeneID\tSymbol\tDescription\tGeneType\n1\tSAME\tone\tprotein-coding\n2\tSAME\ttwo\tlncRNA\n",
        encoding="utf-8",
    )
    frame = load_annotation(p)
    assert frame.gene_id.is_unique
    assert list(frame.symbol) == ["SAME", "SAME"]
    p.write_text("GeneID\tSymbol\n1\tA\n1\tB\n", encoding="utf-8")
    with pytest.raises(ValueError, match="DUPLICATE_GENE_ID"):
        load_annotation(p)


def test_reactome_filters_species_and_duplicate_rows(tmp_path):
    p = tmp_path / "r.tsv"
    row = "1\tR-HSA-1\tu\tOne\tTAS\tHomo sapiens\n"
    p.write_text(row + row + "2\tR-MMU-1\tu\tMouse\tIEA\tMus musculus\n", encoding="utf-8")
    paths = load_reactome(p)
    assert set(paths) == {"R-HSA-1"}
    assert paths["R-HSA-1"].genes == frozenset({"1"})


def test_annotation_merge_preserves_unknown_ids_and_duplicate_symbols(tmp_path):
    import pandas as pd
    from parkinson_functional import annotate_results

    path = tmp_path / "genes.tsv"
    path.write_text(
        "GeneID\tSymbol\tdescription\ttype_of_gene\n1\tSAME\tone\tprotein-coding\n2\tSAME\ttwo\tlncRNA\n",
        encoding="utf-8",
    )
    annotation = load_annotation(path)
    result = annotate_results(
        pd.DataFrame({"feature_id": ["2", "9", "1"], "effect": [3, 4, 5]}), annotation
    )
    assert list(result.feature_id) == ["2", "9", "1"]
    assert list(result.effect) == [3, 4, 5]
    assert result.symbol.isna().sum() == 1
    assert list(result.symbol.dropna()) == ["SAME", "SAME"]
    assert list(result.name.dropna()) == ["two", "one"]


def test_empty_hit_family_and_background_size_filter():
    paths = {
        "R-HSA-1": Pathway("one", frozenset({"1", "2", "9", "10"})),
        "R-HSA-2": Pathway("two", frozenset({"3", "4"})),
    }
    table, audit = overrepresentation(set(), {"1", "2", "3", "4"}, paths, min_size=2, max_size=2)
    assert len(table) == audit["tested_pathways"] == 2
    assert (table.p_value == 1).all()
    assert (table.q_value == 1).all()
    assert (table.pathway_background_count == 2).all()
    empty, audit = overrepresentation(set(), set(), paths)
    assert empty.empty
    assert audit["tested_pathways"] == 0


def test_overlap_symbols_do_not_collapse_entrez_ids():
    paths = {"R-HSA-1": Pathway("one", frozenset({"1", "2"}))}
    table, _ = overrepresentation(
        {"1", "2"}, {"1", "2"}, paths, {"1": "SAME", "2": "SAME"}, min_size=1
    )
    assert table.iloc[0].overlap_ids == "1;2"
    assert table.iloc[0].overlap_symbols == "SAME;SAME"
    assert table.iloc[0].overlap_count == 2


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_probability_is_rejected(value):
    with pytest.raises(ValueError, match="INVALID_P_VALUE"):
        benjamini_hochberg([value])


def test_non_entrez_human_reactome_rows_are_rejected(tmp_path):
    path = tmp_path / "accession.tsv"
    path.write_text("NC_012920\tR-HSA-1\tu\tOne\tTAS\tHomo sapiens\n", encoding="utf-8")
    with pytest.raises(ValueError, match="REACTOME_HUMAN_ID_INVALID"):
        load_reactome(path)
