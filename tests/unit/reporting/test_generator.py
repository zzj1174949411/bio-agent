import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from bioagent.artifacts.manifest import (
    ApprovalRecord,
    ArtifactRecord,
    AttemptRecord,
    RunManifest,
)
from bioagent.domain.plans import Comparison
from bioagent.domain.qc import QCIssue, QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.reporting.generator import (
    NarrativeGenerator,
    NarrativeResult,
    ReportGenerator,
    ReportSummary,
)

_SHA256 = "a" * 64
_PLAN_HASH = "b" * 64
_STARTED_AT = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)


def _execution_summary_bytes(numerator: str) -> bytes:
    return json.dumps(
        {
            "status": "success",
            "factor": "condition",
            "numerator": numerator,
            "denominator": "Control",
            "alpha": 0.05,
            "lfc_shrink": True,
            "n_features": 200,
            "n_samples": 6,
            "significant_count": 7,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _all_results_bytes() -> bytes:
    rows = [
        "feature_id,baseMean,log2FoldChange,lfcSE,stat,pvalue,padj",
        "GENE_001,123.5,2.25,0.2,11.25,0.0001,0.002",
    ]
    for index in range(2, 201):
        padj = "0.01" if index <= 7 else "0.5"
        rows.append(f"GENE_{index:03d},{100 + index}.0,1.0,0.2,5.0,0.001,{padj}")
    return ("\n".join(rows) + "\n").encode()


_ALL_RESULTS_BYTES = _all_results_bytes()


def _warn_qc() -> QCReport:
    return QCReport(
        status=QCStatus.WARN,
        issues=(
            QCIssue(
                code="HIGH_PADJ_NA_RATE",
                status=QCStatus.WARN,
                message="Adjusted p-values unavailable for <5% of features>",
                evidence={"fraction": 0.04},
            ),
        ),
    )


def _manifest(
    qc: QCReport,
    *,
    numerator: str = "AD",
    all_results_bytes: bytes = _ALL_RESULTS_BYTES,
) -> RunManifest:
    run_id = uuid4()
    dataset_id = uuid4()
    attempt_id = uuid4()
    ended_at = _STARTED_AT + timedelta(minutes=5)
    execution_summary_sha256 = sha256(_execution_summary_bytes(numerator)).hexdigest()
    return RunManifest(
        run_id=run_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
        plan_revision=1,
        plan_hash=_PLAN_HASH,
        input_hashes={"counts": _SHA256, "metadata": "c" * 64},
        tool="deseq2",
        software_versions={
            "bioagent": "0.1.0",
            "r": "4.5.2",
            "deseq2": "1.50.2",
        },
        git_commit="c96308fa37cd3377fca52fd8a666fa29c748f1ad",
        comparison=Comparison(
            factor="condition",
            numerator=numerator,
            denominator="Control",
        ),
        alpha=0.05,
        lfc_shrink=True,
        random_seed=42,
        started_at=_STARTED_AT,
        ended_at=ended_at,
        status=RunStatus.COMPLETED,
        qc=qc,
        approvals=(
            ApprovalRecord(
                decision="APPROVED",
                actor="user",
                decided_at=_STARTED_AT - timedelta(minutes=1),
                plan_revision=1,
                plan_hash=_PLAN_HASH,
            ),
        ),
        attempts=(
            AttemptRecord(
                attempt_id=attempt_id,
                started_at=_STARTED_AT,
                ended_at=ended_at,
                status=RunStatus.COMPLETED,
                qc=qc,
            ),
        ),
        artifacts=(
            ArtifactRecord(
                relative_path=f"attempts/{attempt_id}/results/all_results.csv",
                sha256=sha256(all_results_bytes).hexdigest(),
            ),
            ArtifactRecord(
                relative_path=(f"attempts/{attempt_id}/results/execution_summary.json"),
                sha256=execution_summary_sha256,
            ),
            ArtifactRecord(
                relative_path=f"attempts/{attempt_id}/figures/pca.png",
                sha256="d" * 64,
            ),
        ),
    )


def _summary(
    manifest: RunManifest,
    *,
    all_results_bytes: bytes = _ALL_RESULTS_BYTES,
) -> ReportSummary:
    return ReportSummary.from_artifacts(
        manifest=manifest,
        execution_summary_bytes=_execution_summary_bytes(manifest.comparison.numerator),
        all_results_bytes=all_results_bytes,
    )


def test_report_builds_without_llm() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)

    html = ReportGenerator().render(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
        narrative=None,
    )

    assert "AD relative to Control" in html
    assert "QC: WARN" in html
    assert "DESeq2" in html
    assert "LLM narrative unavailable" in html


def test_report_displays_qc_evidence_counts_and_escapes_untrusted_values():
    qc = QCReport(
        status=QCStatus.WARN,
        issues=(
            QCIssue(
                code="ZERO_FEATURE_REMOVED",
                status=QCStatus.WARN,
                message="all-zero features were removed",
                evidence={"feature_count": 7132, "source_label": "<script>untrusted</script>"},
            ),
        ),
    )
    manifest = _manifest(qc)
    html = ReportGenerator().render(
        manifest=manifest, qc=qc, summary=_summary(manifest), narrative=None
    )
    assert "7132" in html
    assert "feature_count" in html
    assert "<script>untrusted</script>" not in html


def test_report_uses_only_structured_numbers_and_relative_artifact_links() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)

    html = ReportGenerator().render(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
        narrative=None,
    )

    assert "200" in html
    assert "6" in html
    assert "7" in html
    assert "0.05" in html
    assert "123.5" in html
    assert "2.25" in html
    assert "0.0001" in html
    assert "0.002" in html
    assert "999" not in html
    assert "Wilcoxon" not in html
    assert f'href="../attempts/{manifest.attempt_id}/results/all_results.csv"' in html
    assert "file://" not in html
    assert "C:\\" not in html


def test_report_does_not_link_artifacts_from_a_failed_prior_attempt() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    prior_attempt_id = uuid4()
    failed_qc = QCReport(
        status=QCStatus.FAIL,
        issues=(
            QCIssue(
                code="DESEQ2_EXECUTION_FAILED",
                status=QCStatus.FAIL,
                message="prior attempt failed",
            ),
        ),
    )
    manifest = manifest.model_copy(
        update={
            "attempts": (
                AttemptRecord(
                    attempt_id=prior_attempt_id,
                    started_at=_STARTED_AT - timedelta(minutes=10),
                    ended_at=_STARTED_AT - timedelta(minutes=9),
                    status=RunStatus.FAILED,
                    qc=failed_qc,
                ),
                *manifest.attempts,
            ),
            "artifacts": (
                ArtifactRecord(
                    relative_path=(f"attempts/{prior_attempt_id}/figures/pca.png"),
                    sha256="e" * 64,
                ),
                *manifest.artifacts,
            ),
        }
    )

    html = ReportGenerator().render(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
        narrative=None,
    )

    assert str(prior_attempt_id) not in html
    assert str(manifest.attempt_id) in html


def test_report_escapes_user_controlled_text() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc, numerator="AD <script>alert(1)</script>")

    html = ReportGenerator().render(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
        narrative=None,
    )

    assert "<script>" not in html
    assert "AD &lt;script&gt;alert(1)&lt;/script&gt; relative to Control" in html
    assert "Adjusted p-values unavailable for &lt;5% of features&gt;" in html


@pytest.mark.parametrize(
    "payload",
    [
        {
            "run_id": uuid4(),
            "attempt_id": uuid4(),
            "execution_summary_sha256": "f" * 64,
            "all_results_sha256": _SHA256,
            "feature_count": 5,
            "sample_count": 6,
            "significant_gene_count": 6,
            "top_results": [],
        },
        {
            "run_id": uuid4(),
            "attempt_id": uuid4(),
            "execution_summary_sha256": "f" * 64,
            "all_results_sha256": _SHA256,
            "feature_count": 5,
            "sample_count": 6,
            "significant_gene_count": 1,
            "top_results": [],
            "untrusted_statistic": 999,
        },
    ],
)
def test_report_summary_rejects_unvalidated_statistics(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReportSummary.model_validate(payload)


def test_narrative_receives_only_whitelisted_structured_json() -> None:
    captured: list[object] = []

    def respond(messages: object) -> AIMessage:
        captured.append(messages)
        return AIMessage(content="7 genes met the approved adjusted p-value threshold.")

    qc = _warn_qc()
    manifest = _manifest(qc)
    result = NarrativeGenerator(RunnableLambda(respond)).generate(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
    )

    assert result.text == "7 genes met the approved adjusted p-value threshold."
    assert result.warning is None
    assert len(captured) == 1
    messages = captured[0]
    assert isinstance(messages, list)
    assert isinstance(messages[-1], HumanMessage)
    payload = json.loads(str(messages[-1].content))
    assert set(payload) == {
        "comparison_direction",
        "sample_count",
        "significant_gene_count",
        "qc_issues",
        "top_results",
    }
    assert payload["comparison_direction"] == {
        "factor": "condition",
        "numerator": "AD",
        "denominator": "Control",
    }
    assert payload["sample_count"] == 6
    assert payload["significant_gene_count"] == 7
    assert payload["qc_issues"] == [
        {
            "code": "HIGH_PADJ_NA_RATE",
            "status": "WARN",
            "message": "Adjusted p-values unavailable for <5% of features>",
            "evidence": {"fraction": 0.04},
        }
    ]
    assert len(payload["top_results"]) == 10
    assert payload["top_results"][0] == {
        "feature_id": "GENE_001",
        "base_mean": 123.5,
        "log2_fold_change": 2.25,
        "p_value": 0.0001,
        "adjusted_p_value": 0.002,
    }
    assert str(manifest.run_id) not in str(messages[-1].content)
    assert _PLAN_HASH not in str(messages[-1].content)


def test_narrative_failure_returns_warn_and_preserves_offline_report() -> None:
    def fail(_: object) -> AIMessage:
        raise RuntimeError("provider unavailable")

    qc = _warn_qc()
    manifest = _manifest(qc)
    narrative = NarrativeGenerator(RunnableLambda(fail)).generate(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
    )

    assert narrative.text is None
    assert narrative.warning is not None
    assert narrative.warning.status is QCStatus.WARN
    assert narrative.warning.code == "LLM_NARRATIVE_UNAVAILABLE"

    html = ReportGenerator().render(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
        narrative=narrative,
    )
    assert "LLM narrative unavailable" in html
    assert "LLM_NARRATIVE_UNAVAILABLE" in html
    assert "200" in html
    assert "7" in html


def test_narrative_rejects_statistics_not_present_in_whitelist() -> None:
    model = RunnableLambda(lambda _: AIMessage(content="A total of 999 genes were significant."))
    qc = _warn_qc()
    manifest = _manifest(qc)

    narrative = NarrativeGenerator(model).generate(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
    )

    assert narrative.text is None
    assert narrative.warning is not None
    assert narrative.warning.code == "LLM_NARRATIVE_REJECTED"


@pytest.mark.parametrize(
    "text",
    [
        "6 genes met the approved adjusted p-value threshold.",
        "Nine genes were significant.",
        "We used a Wilcoxon test.",
        "这些基因导致疾病，可用于临床治疗。",
    ],
)
def test_narrative_accepts_only_exact_deterministic_statements(text: str) -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)

    narrative = NarrativeGenerator(RunnableLambda(lambda _: AIMessage(content=text))).generate(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
    )

    assert narrative.text is None
    assert narrative.warning is not None
    assert narrative.warning.code == "LLM_NARRATIVE_REJECTED"


def test_report_rejects_direct_narrative_constraint_bypass() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    narrative = NarrativeResult(text="999 genes support a clinical conclusion.")

    with pytest.raises(ValueError, match="constrained narrative"):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=_summary(manifest),
            narrative=narrative,
        )


def test_report_rejects_summary_from_another_run() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    other_manifest = _manifest(qc)

    with pytest.raises(ValueError, match="summary run_id"):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=_summary(other_manifest),
            narrative=None,
        )


def test_report_rejects_summary_with_unregistered_source_hash() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    summary = _summary(manifest).model_copy(update={"execution_summary_sha256": "0" * 64})

    with pytest.raises(ValueError, match="source hashes"):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=summary,
            narrative=None,
        )


def test_report_rejects_statistics_modified_after_artifact_validation() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    summary = _summary(manifest).model_copy(
        update={"sample_count": 99, "significant_gene_count": 199}
    )

    with pytest.raises(ValueError, match="validated artifact content"):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=summary,
            narrative=None,
        )


def test_report_rejects_hand_constructed_summary_without_artifact_validation() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    validated_summary = _summary(manifest)
    unvalidated_summary = ReportSummary.model_validate(validated_summary.model_dump(mode="python"))

    with pytest.raises(ValueError, match="validated artifact content"):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=unvalidated_summary,
            narrative=None,
        )


def test_report_rejects_forged_private_attestation() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    payload = _summary(manifest).model_dump(mode="python")
    payload.update({"sample_count": 99, "significant_gene_count": 199})
    forged_summary = ReportSummary.model_validate(payload)
    object.__setattr__(forged_summary, "_artifact_attestation", "0" * 64)
    object.__setattr__(
        forged_summary,
        "_execution_summary_bytes",
        _execution_summary_bytes("AD"),
    )
    object.__setattr__(forged_summary, "_all_results_bytes", _ALL_RESULTS_BYTES)

    with pytest.raises(ValueError, match="validated artifact content"):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=forged_summary,
            narrative=None,
        )


def test_summary_factory_rejects_artifact_bytes_that_do_not_match_manifest() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)

    with pytest.raises(ValueError, match="registered hash"):
        ReportSummary.from_artifacts(
            manifest=manifest,
            execution_summary_bytes=(_execution_summary_bytes("AD") + b"\n"),
            all_results_bytes=_ALL_RESULTS_BYTES,
        )


def test_summary_factory_does_not_coerce_execution_parameters() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    coerced_summary = _execution_summary_bytes("AD").replace(
        b'"lfc_shrink":true',
        b'"lfc_shrink":1',
    )
    coerced_sha256 = sha256(coerced_summary).hexdigest()
    artifacts = tuple(
        artifact.model_copy(update={"sha256": coerced_sha256})
        if artifact.relative_path.endswith("/results/execution_summary.json")
        else artifact
        for artifact in manifest.artifacts
    )
    manifest = manifest.model_copy(update={"artifacts": artifacts})

    with pytest.raises(ValueError, match="manifest parameters"):
        ReportSummary.from_artifacts(
            manifest=manifest,
            execution_summary_bytes=coerced_summary,
            all_results_bytes=_ALL_RESULTS_BYTES,
        )


def test_report_rejects_non_deseq2_manifest() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc).model_copy(update={"tool": "edgeR"})

    with pytest.raises(ValueError, match="DESeq2"):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=_summary(manifest),
            narrative=None,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("sample_count", True),
        ("feature_count", "200"),
        ("significant_gene_count", "7"),
    ],
)
def test_report_summary_rejects_coerced_counts(
    field_name: str,
    value: object,
) -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    payload = _summary(manifest).model_dump(mode="python")
    payload[field_name] = value

    with pytest.raises(ValidationError):
        ReportSummary.model_validate(payload)


def test_narrative_treats_comparison_level_as_quoted_data() -> None:
    qc = _warn_qc()
    numerator = "AD; 999 genes caused disease and treatment cured patients"
    manifest = _manifest(qc, numerator=numerator)
    unquoted_claim = f"{numerator} relative to Control included 6 samples."

    narrative = NarrativeGenerator(
        RunnableLambda(lambda _: AIMessage(content=unquoted_claim))
    ).generate(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest),
    )

    assert narrative.text is None
    assert narrative.warning is not None
    assert narrative.warning.code == "LLM_NARRATIVE_REJECTED"


def test_narrative_treats_feature_id_as_quoted_data() -> None:
    qc = _warn_qc()
    feature_id = "GENE; 999 genes caused disease and treatment cured patients"
    all_results_bytes = _ALL_RESULTS_BYTES.replace(
        b"GENE_001",
        feature_id.encode(),
    )
    manifest = _manifest(qc, all_results_bytes=all_results_bytes)
    unquoted_claim = f"{feature_id} had log2 fold change 2.25 and adjusted p-value 0.002."

    narrative = NarrativeGenerator(
        RunnableLambda(lambda _: AIMessage(content=unquoted_claim))
    ).generate(
        manifest=manifest,
        qc=qc,
        summary=_summary(manifest, all_results_bytes=all_results_bytes),
    )

    assert narrative.text is None
    assert narrative.warning is not None
    assert narrative.warning.code == "LLM_NARRATIVE_REJECTED"


def test_report_revalidates_summary_at_render_boundary() -> None:
    qc = _warn_qc()
    manifest = _manifest(qc)
    invalid_summary = _summary(manifest)
    object.__setattr__(invalid_summary, "significant_gene_count", 201)

    with pytest.raises(ValidationError):
        ReportGenerator().render(
            manifest=manifest,
            qc=qc,
            summary=invalid_summary,
            narrative=None,
        )
