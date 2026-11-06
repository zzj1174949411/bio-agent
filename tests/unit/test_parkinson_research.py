"""Scientific comparison contracts; no R, private configuration or network."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from parkinson_research import (  # noqa: E402
    SENSITIVITIES,
    compare_results,
    functional_analysis,
    stability_table,
    verify_inputs,
)


def results():
    return pd.DataFrame(
        {
            "feature_id": ["1", "2", "3"],
            "log2FoldChange": [1.0, -2.0, 0.2],
            "padj": [0.05, 0.01, None],
            "baseMean": [100, 200, 1],
        }
    )


def test_model_comparison_aligns_ids_instead_of_row_positions():
    baseline = results()
    reordered = baseline.iloc[::-1].copy()
    value = compare_results(baseline, reordered)
    assert value["common_padj_genes"] == 2
    assert value["shared_significant"] == 2
    assert value["lfc_pearson_common_padj"] == pytest.approx(1)
    assert value["direction_agreement_common_padj"] == 1


def test_comparison_rejects_duplicate_gene_ids():
    with pytest.raises(ValueError, match="DUPLICATE_FEATURE_ID"):
        compare_results(results(), pd.concat([results(), results().iloc[:1]]))


def test_stability_distinguishes_direction_from_significance_and_missingness():
    main = results()
    alternative = results()
    alternative.loc[0, "padj"] = 0.2
    alternative.loc[1, "log2FoldChange"] = 1
    stable = stability_table({"full": main, "rin5": alternative}, ["rin5"])
    first = stable.set_index("feature_id").loc["1"]
    assert first["main_significant"]
    assert first["all_same_direction"]
    assert not first["all_significant_same_direction"]
    assert not stable.set_index("feature_id").loc["2", "all_same_direction"]
    assert not stable.set_index("feature_id").loc["3", "all_available"]


def test_changed_research_input_blocks_comparison(tmp_path):
    from hashlib import sha256

    path = tmp_path / "counts.tsv"
    path.write_bytes(b"frozen input")
    audit = {"counts": {"path": "counts.tsv", "sha256": sha256(path.read_bytes()).hexdigest()}}
    assert verify_inputs(audit, tmp_path)["counts"]["verified"]
    path.write_bytes(b"modified")
    with pytest.raises(ValueError, match="INPUT_HASH_CHANGED"):
        verify_inputs(audit, tmp_path)


def test_functional_driver_uses_common_tested_genes_and_keeps_entrez_ids(tmp_path):
    ids = [str(i) for i in range(1, 13)]
    main = pd.DataFrame(
        {
            "feature_id": ids,
            "log2FoldChange": [1.0] * 12,
            "padj": [0.05] + [0.5] * 11,
            "baseMean": [100] * 12,
        }
    )
    models = {
        name: main.copy()
        for name in ["full", "unadjusted", *SENSITIVITIES, "unadjusted_uniform", "full_uniform"]
    }
    models["rin6"].loc[11, "padj"] = float("nan")
    stability_table(models, SENSITIVITIES).to_csv(tmp_path / "gene_stability.csv", index=False)
    annotation = tmp_path / "annotation.tsv"
    pd.DataFrame({"GeneID": ids, "Symbol": ["SNCA"] + ["SAME"] * 11}).to_csv(
        annotation, sep="\t", index=False
    )
    reactome = tmp_path / "reactome.tsv"
    reactome.write_text("".join(f"{gene}\tR-HSA-1\tu\tOne\tTAS\tHomo sapiens\n" for gene in ids))
    functional_analysis(models, annotation, reactome, tmp_path)
    native = pd.read_csv(tmp_path / "ora_full_up.csv")
    common = pd.read_csv(tmp_path / "ora_common_full_up.csv")
    assert native.loc[0, "background_count"] == 12
    assert common.loc[0, "background_count"] == 11
    assert native.loc[0, "hit_count"] == 1  # includes the equality FDR boundary
    annotated = pd.read_csv(tmp_path / "full_annotated.csv")
    assert len(annotated) == 12
    assert annotated.feature_id.is_unique
    assert (annotated.symbol == "SAME").sum() == 11
