from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    numerator: str = Field(min_length=1)
    denominator: str = Field(min_length=1)

    @model_validator(mode="after")
    def levels_must_differ(self) -> "Comparison":
        if self.numerator == self.denominator:
            raise ValueError("numerator and denominator must differ")
        return self


class AnalysisOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alpha: float = Field(default=0.05, gt=0, lt=1)
    lfc_shrink: bool = True
    random_seed: int = Field(default=42, ge=0)


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    analysis_type: Literal["bulk_differential_expression"] = (
        "bulk_differential_expression"
    )
    tool: Literal["deseq2"] = "deseq2"
    dataset_id: str = Field(min_length=36, max_length=36)
    comparison: Comparison
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
