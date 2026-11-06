"""Deterministic follow-up of the user-authorized Parkinson research models.

This script is separate from production analysis tools. It never loads model
credentials, changes old runs, or accepts executable formulas from data.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data/task50/live-20261026-03"
OLD_RUN = OLD / "runs/cfce4945-30ac-49a6-a8bd-ae4f6ed3990a"
SENSITIVITIES = ["rin5", "rin6", "age_overlap", "pmi_influence"]
PD_PANEL = [
    "SNCA",
    "LRRK2",
    "PRKN",
    "PINK1",
    "PARK7",
    "VPS35",
    "GBA1",
    "TH",
    "DDC",
    "SLC6A3",
    "SLC18A2",
]


def save(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def verify_inputs(audit: dict, root: Path = ROOT) -> dict:
    verified = {}
    for name, value in audit.items():
        if not isinstance(value, dict) or "sha256" not in value:
            continue
        path = (root / value["path"]).resolve()
        path.relative_to(root.resolve())
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != value["sha256"]:
            raise ValueError("INPUT_HASH_CHANGED: " + name)
        verified[name] = {**value, "verified": True}
    return verified


def indexed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["feature_id"] = result["feature_id"].astype(str)
    if result["feature_id"].duplicated().any():
        raise ValueError("DUPLICATE_FEATURE_ID")
    return result.set_index("feature_id")


def compare_results(baseline: pd.DataFrame, alternative: pd.DataFrame) -> dict:
    left, right = indexed(baseline), indexed(alternative)
    common = left.index.intersection(right.index)
    left, right = left.loc[common], right.loc[common]
    available = np.isfinite(left["padj"]) & np.isfinite(right["padj"])
    lfc_available = (
        available & np.isfinite(left["log2FoldChange"]) & np.isfinite(right["log2FoldChange"])
    )
    left_significant, right_significant = left.padj.le(0.05), right.padj.le(0.05)
    x = left.loc[lfc_available, "log2FoldChange"]
    y = right.loc[lfc_available, "log2FoldChange"]
    varying = len(x) >= 2 and x.nunique() > 1 and y.nunique() > 1
    shared = left_significant & right_significant
    same_direction = np.sign(left.log2FoldChange) == np.sign(right.log2FoldChange)
    return {
        "overlapping_genes": len(common),
        "common_padj_genes": int(available.sum()),
        "shared_significant": int(shared.sum()),
        "shared_significant_same_direction": int((shared & same_direction).sum()),
        "left_significant_common_padj": int((left_significant & available).sum()),
        "right_significant_common_padj": int((right_significant & available).sum()),
        "lost_significance_common_padj": int(
            (left_significant & ~right_significant & available).sum()
        ),
        "gained_significance_common_padj": int(
            (~left_significant & right_significant & available).sum()
        ),
        "significant_opposite_direction": int((shared & ~same_direction).sum()),
        "direction_agreement_common_padj": float(same_direction[lfc_available].mean())
        if lfc_available.any()
        else None,
        "lfc_pearson_common_padj": float(np.corrcoef(x, y)[0, 1]) if varying else None,
        "lfc_spearman_common_padj": float(spearmanr(x, y).statistic) if varying else None,
    }


def stability_table(models: dict[str, pd.DataFrame], alternatives: list[str]) -> pd.DataFrame:
    main = indexed(models["full"])
    result = main[["log2FoldChange", "padj", "baseMean"]].rename(
        columns={"log2FoldChange": "main_log2FoldChange", "padj": "main_padj"}
    )
    result["main_significant"] = result.main_padj.le(0.05)
    result["all_available"] = np.isfinite(result.main_padj)
    result["all_same_direction"] = np.isfinite(result.main_log2FoldChange)
    result["all_significant_same_direction"] = result.main_significant
    for name in alternatives:
        current = indexed(models[name]).reindex(result.index)
        finite_lfc = np.isfinite(current.log2FoldChange)
        same = finite_lfc & (np.sign(current.log2FoldChange) == np.sign(result.main_log2FoldChange))
        result[name + "_log2FoldChange"] = current.log2FoldChange
        result[name + "_padj"] = current.padj
        result["all_available"] &= np.isfinite(current.padj)
        result["all_same_direction"] &= same
        result["all_significant_same_direction"] &= current.padj.le(0.05) & same
    return result.reset_index()


def baseline_parity(frame: pd.DataFrame) -> dict:
    old = pd.read_csv(next(OLD_RUN.rglob("all_results.csv")), dtype={"feature_id": str})
    left, right = indexed(old).sort_index(), indexed(frame).sort_index()
    if not left.index.equals(right.index):
        raise ValueError("BASELINE_FEATURE_PARITY_FAILED")
    maximum = {}
    for name in ["log2FoldChange", "pvalue", "padj"]:
        a, b = left[name].to_numpy(), right[name].to_numpy()
        if not np.allclose(a, b, rtol=1e-8, atol=1e-10, equal_nan=True):
            raise ValueError("BASELINE_NUMERIC_PARITY_FAILED: " + name)
        finite = np.isfinite(a) & np.isfinite(b)
        maximum[name] = float(np.max(np.abs(a[finite] - b[finite])))
    return {"genes": len(left), "rtol": 1e-8, "atol": 1e-10, "max_absolute_difference": maximum}


def coverage_audit(output: Path) -> None:
    from verify_parkinson_live import traits

    source = json.loads((ROOT / "data/task50/research/GSE205450.json").read_text(encoding="utf-8"))
    selected = set(pd.read_csv(ROOT / "data/task50/review-20261026/samples.csv").gsm)
    rows, diagnoses = [], {}
    for sample in source["samples"]:
        values = traits(sample)
        diagnoses.setdefault(values["patient"], []).append(
            (sample["accession"], values["disease"], values["region"])
        )
        if values["region"] == "CAU":
            rows.append(
                {
                    "gsm": sample["accession"],
                    "group": values["disease"],
                    "available": sample["accession"] in selected,
                    "age": values["age at death"],
                    "rin": values["rna integrity number (rin)"],
                }
            )
    pd.DataFrame(rows).to_csv(output / "coverage_samples.csv", index=False)
    conflicts = [
        {"patient": patient, "samples": samples}
        for patient, samples in diagnoses.items()
        if len({row[1] for row in samples}) > 1
    ]
    save(output / "source_label_conflicts.json", conflicts)
    aggregate = pd.DataFrame(rows)
    aggregate["age"] = pd.to_numeric(aggregate.age)
    aggregate["rin"] = pd.to_numeric(aggregate.rin)
    aggregate.groupby(["group", "available"]).agg(
        n=("gsm", "size"), age_median=("age", "median"), rin_median=("rin", "median")
    ).reset_index().to_csv(output / "coverage_summary.csv", index=False)


def qc_analysis(models_path: Path, output: Path, bh_adjust) -> None:
    metadata = pd.read_csv(models_path / "prepared_metadata.csv").set_index("sample_id")
    sample_qc = pd.read_csv(models_path / "full/sample_diagnostics.csv").set_index("sample_id")
    metadata.join(sample_qc).to_csv(output / "sample_qc.csv")
    pca = pd.read_csv(models_path / "full/pca.csv").set_index("sample_id")
    values = metadata.join(sample_qc).join(pca)
    values["log10_library_size"] = np.log10(values.library_size)
    values["condition_PD"] = values.condition.eq("PD").astype(int)
    rows = []
    for component in ["PC1", "PC2", "PC3"]:
        for variable in ["age", "rin", "pmi", "log10_library_size", "condition_PD"]:
            result = spearmanr(values[component], values[variable])
            rows.append(
                {
                    "component": component,
                    "covariate": variable,
                    "rho": float(result.statistic),
                    "pvalue": float(result.pvalue),
                }
            )
    table = pd.DataFrame(rows)
    table["padj"] = bh_adjust(table.pvalue.to_numpy())
    table.to_csv(output / "pca_covariate_correlations.csv", index=False)
    values.groupby("condition")[["age", "rin", "pmi", "library_size", "detected_genes"]].agg(
        ["count", "median", "min", "max"]
    ).to_csv(output / "cohort_descriptives.csv")


def functional_analysis(
    models: dict, annotation_path: Path, reactome_path: Path, output: Path
) -> None:
    from parkinson_functional import load_annotation, load_reactome, overrepresentation

    annotation = load_annotation(annotation_path).rename(columns={"gene_id": "feature_id"})
    annotation["feature_id"] = annotation.feature_id.astype(str)
    if annotation.feature_id.duplicated().any():
        raise ValueError("DUPLICATE_ANNOTATION_ID")
    pathways = load_reactome(reactome_path)
    symbols = annotation.set_index("feature_id").symbol.to_dict()
    mapped = set().union(*(pathway.genes for pathway in pathways.values()))
    annotated = models["full"].merge(annotation, on="feature_id", how="left", validate="one_to_one")
    annotated.to_csv(output / "full_annotated.csv", index=False)
    stability = pd.read_csv(output / "gene_stability.csv", dtype={"feature_id": str})
    stability.merge(annotation, on="feature_id", how="left", validate="one_to_one").to_csv(
        output / "gene_stability_annotated.csv", index=False
    )
    panel = annotated[annotated.symbol.isin(PD_PANEL)].copy()
    panel["panel_order"] = panel.symbol.map({symbol: i for i, symbol in enumerate(PD_PANEL)})
    panel.sort_values("panel_order").drop(columns="panel_order").to_csv(
        output / "pd_gene_panel.csv", index=False
    )
    save(
        output / "annotation_audit.json",
        {
            "result_genes": len(annotated),
            "annotated_genes": int(annotated.symbol.notna().sum()),
            "unmapped_ids": annotated.loc[annotated.symbol.isna(), "feature_id"].tolist(),
            "duplicated_symbols_retained": int(annotation.symbol.duplicated(keep=False).sum()),
            "panel_missing_symbols": sorted(set(PD_PANEL) - set(panel.symbol)),
            "reactome_total_human_genes": len(mapped),
            "reactome_total_pathways": len(pathways),
        },
    )
    finite = {
        name: set(frame.loc[np.isfinite(frame.padj), "feature_id"]) & mapped
        for name, frame in models.items()
    }
    comparison_models = ["unadjusted", "full", *SENSITIVITIES, "unadjusted_uniform", "full_uniform"]
    common = set.intersection(*(finite[name] for name in comparison_models))
    rows = []
    common_tables = []
    for mode, names in [("native", ["full"]), ("common", comparison_models)]:
        for name in names:
            universe = finite[name] if mode == "native" else common
            pd.DataFrame({"feature_id": sorted(universe)}).to_csv(
                output / f"background_{mode}_{name}.csv", index=False
            )
            for direction in ["up", "down"]:
                table = models[name]
                chosen = table.padj.le(0.05) & (
                    table.log2FoldChange.gt(0) if direction == "up" else table.log2FoldChange.lt(0)
                )
                original_hits = set(table.loc[chosen, "feature_id"])
                hits = original_hits & universe
                result, audit = overrepresentation(
                    hits, universe, pathways, symbols=symbols, min_size=10, max_size=500
                )
                result = result.rename(
                    columns={
                        "name": "pathway_name",
                        "overlap_count": "overlap",
                        "pathway_background_count": "pathway_size",
                        "p_value": "pvalue",
                        "q_value": "padj",
                    }
                )
                # Some resource adapters already use pathway_name; no symbol-based joining.
                filename = (
                    f"ora_{name}_{direction}"
                    if mode == "native"
                    else f"ora_common_{name}_{direction}"
                )
                result.to_csv(output / (filename + ".csv"), index=False)
                save(output / (filename + "_audit.json"), audit)
                rows.append(
                    {
                        "background": mode,
                        "model": name,
                        "direction": direction,
                        "universe": len(universe),
                        "all_significant": len(original_hits),
                        "mapped_significant": len(hits),
                        "eligible_pathways": len(result),
                        "fdr_pathways": int(result.padj.le(0.05).sum()),
                    }
                )
                if mode == "common":
                    common_tables.append(
                        result[["pathway_id", "pathway_name", "overlap", "padj"]].assign(
                            model=name, direction=direction
                        )
                    )
    pd.DataFrame(rows).to_csv(output / "ora_audit.csv", index=False)
    combined = pd.concat(common_tables)
    combined.to_csv(output / "ora_common_comparisons.csv", index=False)
    pathway_stability = combined.pivot(
        index=["direction", "pathway_id", "pathway_name"], columns="model", values="padj"
    )
    pathway_stability["all_quality_age_pmi_fdr"] = (
        pathway_stability[["full", *SENSITIVITIES]].le(0.05).all(axis=1)
    )
    pathway_stability.reset_index().to_csv(output / "ora_pathway_stability.csv", index=False)
    save(
        output / "stability_summary.json",
        {
            "main_significant": int(stability.main_significant.sum()),
            "main_same_direction_all_variants": int(
                (stability.main_significant & stability.all_same_direction).sum()
            ),
            "main_significant_same_direction_all_variants": int(
                stability.all_significant_same_direction.sum()
            ),
            "strong_effect_main_abs_lfc_ge_1": int(
                (stability.main_significant & stability.main_log2FoldChange.abs().ge(1)).sum()
            ),
            "common_ora_universe": len(common),
        },
    )


def write_report(models_path: Path, output: Path) -> None:
    """Readable report from saved calculations; figures are embedded in the HTML."""
    verify_inputs(json.loads((ROOT / "data/task51/input-audit.json").read_text(encoding="utf-8")))
    model_summary = pd.read_csv(output / "model_summary.csv")
    stability = pd.read_csv(output / "gene_stability.csv")
    significant = stability[stability.main_significant]
    panel = pd.read_csv(output / "pd_gene_panel.csv")
    genes = pd.read_csv(output / "full_annotated.csv")
    comparisons = pd.read_csv(output / "model_comparisons.csv")
    sources = json.loads((output / "resource_audit.json").read_text(encoding="utf-8"))
    parts, markdown = [], []

    def section(title: str, text: str) -> None:
        parts.append(f"<h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>")
        markdown.extend(["## " + title, "", text, ""])

    def table(frame: pd.DataFrame) -> None:
        parts.append(frame.to_html(index=False, escape=True, float_format=lambda x: f"{x:.4g}"))
        # No optional tabulate dependency needed for the plain Markdown table.
        columns = list(frame.columns)
        markdown.append("| " + " | ".join(columns) + " |")
        markdown.append("| " + " | ".join(["---"] * len(columns)) + " |")
        for _, row in frame.iterrows():
            markdown.append("| " + " | ".join(str(x).replace("|", "/") for x in row) + " |")
        markdown.append("")

    section(
        "GSE205450：帕金森尾状核科研深化分析",
        "2026-10-28。研究对象为尸检尾状核（CAU）63名独立供者，PD31、Control32。"
        "本轮在已完成的真实DeepSeek规划与R分析基础上，由用户授权进行协变量调整、质量敏感性和Reactome分析。"
        "新统计全部由确定性R/Python计算，未追加模型调用；这是一项探索性研究，不是诊断模型。",
    )
    section(
        "核心结果与可信范围",
        f"原双组模型8,293个显著基因；主模型调整死亡年龄、性别、RNA完整度RIN和尸检间隔PMI后为{len(significant):,}个。"
        f"四项预定敏感性（RIN≥5、RIN≥6、年龄65–90、去除唯一PMI45小时样本）中，"
        f"{int(significant.all_same_direction.sum()):,}个主显著基因保持变化方向，"
        f"{int(significant.all_significant_same_direction.sum()):,}个还在每项检查中保持FDR≤0.05。"
        "这是同一队列中的敏感性证据，不能代替独立队列验证。显著数减少不等于原结果均为假阳性；"
        "RNA降解、疾病相关组织变化、调整目标变化和样本量都可能影响结果。",
    )
    section(
        "模型、阈值和样本筛选",
        "主模型 ~age_z+sex+rin_z+pmi_z+condition；比较PD/Control；"
        "年龄、RIN、PMI以全63人中心标准化。"
        "所有模型固定alpha=0.05，无log2FC收缩，无额外倍数阈值，只移除各队列全零行。"
        "10个公式/样本规则在查看新拟合结果前固定，但它们基于此前QC提出，不能称预注册。"
        "未调整对照中未定义的病程、痴呆或疾病后用药；未测量的混杂仍可能存在。",
    )
    table(
        model_summary[
            [
                "model",
                "n_samples",
                "significant_up",
                "significant_down",
                "padj_available",
                "pvalue_na",
                "replaced_genes",
            ]
        ]
    )
    section(
        "为什么需要质量敏感性",
        "PD/Control死亡年龄中位数75/68.5岁，RIN中位数6.1/6.9，性别为23男8女/23男9女。"
        "RIN既可能反映技术降解，也可能与疾病和组织状态有关，因此调整RIN可能去除部分疾病相关信号。"
        "质量筛选不是按结果删点；主分析保留全63人，RIN≥5为48人、≥6为42人。"
        "PCA使用VST表达，未回归移除协变量，不能称为‘校正后的PCA’；其相关检验只作探索诊断。",
    )
    table(pd.read_csv(output / "pca_covariate_correlations.csv").sort_values("padj").head(8))
    section(
        "效应方向与显著性分别评估",
        "下表左侧为主模型，右侧为敏感性模型。共同finite padj范围内比较过滤变化；"
        "显著性交集可能随样本数和独立过滤下降，方向一致也不表示效应量完全不变。"
        "全部比较和逐基因数据保存在CSV，未将某个显著基因最多的模型选为最佳。",
    )
    table(
        comparisons.loc[
            comparisons.alternative.isin(SENSITIVITIES),
            [
                "alternative",
                "common_padj_genes",
                "shared_significant_same_direction",
                "lfc_pearson_common_padj",
            ],
        ]
    )
    section(
        "重点帕金森/多巴胺基因",
        "以下11个基因在查看新结果前固定。log2FC>0代表PD表达更高，<0代表更低；"
        "95%区间为未收缩Wald区间，不是全基因同时置信区间。"
        "遗传风险基因在尾状核bulk RNA中不一定差异表达；"
        "RNA变化也不能直接证明蛋白聚集、细胞死亡或药物靶点。",
    )
    table(panel[["feature_id", "symbol", "log2FoldChange", "ci95_low", "ci95_high", "padj"]])
    section(
        "主模型排名靠前的基因",
        "按主模型FDR排序展示前20；这不是新的独立验证或候选优先级模型。完整注释保留Entrez主键，重复符号不合并，未注释行保留。",
    )
    table(genes.sort_values("padj").head(20)[["feature_id", "symbol", "log2FoldChange", "padj"]])
    section(
        "Reactome通路分析的定义",
        "人类Entrez映射；上调、下调分别进行超几何过度代表分析（ORA）。"
        "主分析背景为本模型finite padj且可映射Reactome的基因；只检验背景内10–500个基因的通路。"
        "全部符合大小条件的通路（包含零命中）进入各自方向的BH校正。"
        "另以共同背景比较全模型与四项敏感性，以及统一Cook处理的对照；每个模型/方向是独立探索检验族。"
        "ORA表示差异基因在通路中过度代表，不等于通路活性升高/降低；层级通路共享基因，也不能视为彼此独立的发现。",
    )
    table(pd.read_csv(output / "ora_audit.csv"))
    section(
        "跨质量/年龄/PMI检查的通路结果",
        "以下是在查看全部结果后选取的解释性例子，未减少BH检验族。"
        "‘main_padj’来自主模型自身背景，‘rin6_common_padj’来自固定共同背景；两者不混称同一个检验。"
        "共同背景中73条上调、12条下调通路在主模型及四个敏感性中均达到FDR≤.05；"
        "这些层级重叠条目不等于85个独立生物学机制。",
    )
    themes = [
        ("up", "R-HSA-5660526", "金属离子响应"),
        ("up", "R-HSA-4839726", "染色质组织"),
        ("up", "R-HSA-3371571", "HSF1依赖转录"),
        ("down", "R-HSA-1428517", "有氧呼吸与呼吸电子传递"),
        ("down", "R-HSA-112314", "神经递质受体和突触后信号"),
        ("down", "R-HSA-191273", "胆固醇合成"),
    ]
    pathway_stability = pd.read_csv(output / "ora_pathway_stability.csv").set_index(
        ["direction", "pathway_id"]
    )
    rows = []
    for direction, identity, label in themes:
        native = (
            pd.read_csv(output / f"ora_full_{direction}.csv").set_index("pathway_id").loc[identity]
        )
        common = pathway_stability.loc[(direction, identity)]
        rows.append(
            {
                "theme": label,
                "direction": direction,
                "overlap": native.overlap,
                "pathway_size": native.pathway_size,
                "main_padj": native.padj,
                "rin6_common_padj": common.rin6,
                "all_quality_age_pmi_fdr": common.all_quality_age_pmi_fdr,
            }
        )
    representatives = pd.DataFrame(rows)
    representatives.to_csv(output / "pathway_representatives.csv", index=False)
    table(representatives)
    for direction, label in [("up", "PD较高基因"), ("down", "PD较低基因")]:
        section("Reactome：" + label, "按BH FDR排序；全部结果与命中Entrez ID在对应CSV中。")
        ora = pd.read_csv(output / f"ora_full_{direction}.csv")
        table(
            ora.sort_values(["padj", "pvalue"]).head(12)[
                ["pathway_id", "pathway_name", "overlap", "pathway_size", "fold_enrichment", "padj"]
            ]
        )
    if (output / "interpretation.md").exists():
        note = (output / "interpretation.md").read_text(encoding="utf-8")
        parts.append("<h2>科研解读与交叉核查</h2>")
        parts.extend(
            "<p>" + html.escape(paragraph).replace("\n", "<br>") + "</p>"
            for paragraph in note.split("\n\n")
            if paragraph
        )
        markdown.extend(["## 科研解读与交叉核查", "", note, ""])
    section(
        "异常计数处理：不能忽略的模型差异",
        "原默认双组模型有359个基因发生异常计数替换，含连续协变量的主模型未替换。"
        "另统一关闭替换及Cook筛查后，unadjusted为8,301个显著基因，full仍4,055；"
        "因此总体差异不只由替换机制解释。Entrez3067在默认模型与full之间是唯一两者显著但反向的例子，"
        "其原模型发生替换，统一处理后方向一致，不应称作协变量造成的生物学反转。"
        "gene_diagnostics.max_cooks是DESeq2自动筛查字段，缺失不代表没有高Cook；"
        "另从full cooks assay直接导出full_raw_cooks.csv用于影响诊断。关闭保护的拟合仅为补充诊断。",
    )
    section(
        "来源覆盖与研究局限",
        "NCBI生成矩阵覆盖119/150份公开样本，选择其中CAU63份；原CAU75人缺Control8、PD4，"
        "缺失组在年龄/RIN上存在差异，不能假定随机缺失。原SOFT中PD_10另一脑区PUT样本GSM6212998"
        "标签与其CAU样本GSM6212997冲突；本轮未使用PUT，不自动修正原标签。"
        "bulk混合组织不能区分细胞比例改变与细胞内调控；无细胞去卷积、蛋白实验、独立队列或临床预测验证。"
        "原论文使用作者定量与不同统计方法，本轮用NCBI生成的HISAT2/featureCounts和DESeq2，不能称精确复现原论文。",
    )
    section(
        "来源与可复现性",
        "数据：https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE205450；"
        "原论文：https://www.nature.com/articles/s41467-023-39652-6；"
        "方法：https://www.bioconductor.org/packages/release/bioc/vignettes/DESeq2/inst/doc/DESeq2.html；"
        "Reactome：https://reactome.org/download-data。注释/通路下载时间、版本和hash见resource_audit.json，"
        "原输入核验见input_verification.json，逐文件hash见artifact_manifest.json；"
        "原始双组38,937行的LFC/p/padj与Task50逐值一致（最大差0）。",
    )
    section(
        "注释与通路版本的限制",
        "NCBI原始GRCh38.p13静态注释接口不可用，本轮采用2026-10-27更新的官方人类Gene快照"
        "（194,025条），仅增加符号/名称，不重新分配原始计数。38,937行结果中37,227行获得注释，"
        "其余1,710行保留Entrez ID，不能自动称为未表达或无意义。Reactome接口下载前后均为98；"
        "原映射中224行序列accession另存审计，仅保留人类数字Entrez映射。"
        "旧ID撤销/符号更新与数据库覆盖都可能影响解释，原统计值保持不变。",
    )
    parts.append(
        "<details><summary>官方资源快照</summary><pre>"
        + html.escape(json.dumps(sources, ensure_ascii=False, indent=2))
        + "</pre></details>"
    )
    for path in sorted((output / "figures").glob("*.png")):
        title = path.stem
        image = base64.b64encode(path.read_bytes()).decode("ascii")
        parts.append(f'<h2>{title}</h2><img alt="{title}" src="data:image/png;base64,{image}">')
        markdown.extend([f"![{title}](figures/{path.name})", ""])
    links = sorted(output.glob("*.csv")) + sorted(output.glob("*.json"))
    parts.append(
        "<h2>数据附件</h2><ul>"
        + "".join(
            f'<li><a href="{html.escape(p.name)}">{html.escape(p.name)}</a></li>' for p in links
        )
        + "</ul>"
    )
    document = (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        "<title>帕金森科研深化分析</title><style>"
        "body{max-width:1200px;margin:32px auto;padding:0 24px;"
        "font:16px/1.7 system-ui;color:#24333d}h2{margin-top:38px}"
        "table{border-collapse:collapse;display:block;overflow:auto;font-size:13px}"
        "td,th{padding:7px;border:1px solid #dce2e6;text-align:left}"
        "img{max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        "p{max-width:1000px}</style>" + "\n".join(parts) + "</html>"
    )
    (output / "parkinson-research.html").write_text(document, encoding="utf-8")
    (output / "parkinson-research.md").write_text("\n".join(markdown), encoding="utf-8")
    artifacts = []
    for path in sorted(list(models_path.rglob("*")) + list(output.rglob("*"))):
        if not path.is_file() or path.name == "artifact_manifest.json":
            continue
        artifacts.append(
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        )
    source_files = [
        ROOT / "scripts" / name
        for name in [
            "parkinson_models.R",
            "parkinson_research.py",
            "parkinson_figures.R",
            "parkinson_functional.py",
        ]
    ]
    save(
        output / "artifact_manifest.json",
        {
            "analysis": "Task51, exploratory GSE205450 CAU, 10 deterministic fits",
            "artifacts": artifacts,
            "scripts": [
                {"path": str(p.relative_to(ROOT)), "sha256": sha256(p.read_bytes()).hexdigest()}
                for p in source_files
            ],
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--annotation", type=Path)
    parser.add_argument("--reactome", type=Path)
    parser.add_argument("--resource-audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--finalize", action="store_true", help="Render report/hash inventory after R figures"
    )
    args = parser.parse_args()
    args.models = args.models.resolve()
    args.output = args.output.resolve()
    if args.finalize:
        write_report(args.models, args.output)
        print("Report and artifact manifest written", flush=True)
        return
    supplied = [args.annotation, args.reactome, args.resource_audit]
    if any(path is not None for path in supplied) and not all(
        path is not None for path in supplied
    ):
        parser.error("--annotation, --reactome and --resource-audit must be supplied together")
    if args.output.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output.mkdir(parents=True)
    save(
        args.output / "runtime_versions.json",
        {
            "python": sys.version,
            "packages": {name: version(name) for name in ["numpy", "pandas", "scipy"]},
        },
    )
    audit = json.loads((ROOT / "data/task51/input-audit.json").read_text(encoding="utf-8"))
    save(args.output / "input_verification.json", verify_inputs(audit))
    summaries = json.loads((args.models / "model_summaries.json").read_text(encoding="utf-8"))
    models = {
        name: pd.read_csv(args.models / name / "all_results.csv", dtype={"feature_id": str})
        for name in summaries
    }
    save(args.output / "baseline_parity.json", baseline_parity(models["unadjusted"]))
    comparisons = []
    for name in models:
        comparisons.append(
            {
                "reference": "full",
                "alternative": name,
                **compare_results(models["full"], models[name]),
            }
        )
    comparisons.append(
        {
            "reference": "unadjusted_uniform",
            "alternative": "full_uniform",
            **compare_results(models["unadjusted_uniform"], models["full_uniform"]),
        }
    )
    pd.DataFrame(comparisons).to_csv(args.output / "model_comparisons.csv", index=False)
    stability_table(models, SENSITIVITIES).to_csv(args.output / "gene_stability.csv", index=False)
    pd.DataFrame(
        [
            {
                "model": name,
                **{key: value for key, value in row.items() if not isinstance(value, (list, dict))},
            }
            for name, row in summaries.items()
        ]
    ).to_csv(args.output / "model_summary.csv", index=False)
    coverage_audit(args.output)
    print("Baseline parity and ID-aligned model comparisons verified", flush=True)
    if (
        args.annotation is not None
        and args.reactome is not None
        and args.resource_audit is not None
    ):
        from parkinson_functional import benjamini_hochberg

        save(
            args.output / "resource_audit.json",
            json.loads(args.resource_audit.read_text(encoding="utf-8")),
        )
        save(
            args.output / "used_resources.json",
            [
                {
                    "path": str(path.resolve().relative_to(ROOT)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
                for path in [args.annotation, args.reactome, args.resource_audit]
            ],
        )
        qc_analysis(args.models, args.output, benjamini_hochberg)
        functional_analysis(models, args.annotation, args.reactome, args.output)
        print("Annotation, QC and ORA written", flush=True)


if __name__ == "__main__":
    main()
