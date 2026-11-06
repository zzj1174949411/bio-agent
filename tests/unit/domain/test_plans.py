import pytest
from pydantic import ValidationError

from bioagent.domain.plans import AnalysisPlan, Comparison


def test_comparison_rejects_same_levels() -> None:
    with pytest.raises(ValidationError):
        Comparison(factor="condition", numerator="AD", denominator="AD")


def test_plan_has_only_supported_analysis_and_tool() -> None:
    plan = AnalysisPlan(
        dataset_id="b8b439c9-c576-4f87-ae41-69e0810c38c9",
        comparison=Comparison(
            factor="condition", numerator="AD", denominator="Control"
        ),
    )
    assert plan.analysis_type == "bulk_differential_expression"
    assert plan.tool == "deseq2"
    assert plan.options.alpha == 0.05
