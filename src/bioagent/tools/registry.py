from collections.abc import Iterator, Mapping
from pathlib import Path, PureWindowsPath
from typing import Any, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
    model_validator,
)

from bioagent.artifacts.paths import validate_artifact_relative_path

_EXPECTED_PARAMETERS = {
    "counts_path": ("string", True),
    "metadata_path": ("string", True),
    "output_dir": ("string", True),
    "factor": ("string", True),
    "numerator": ("string", True),
    "denominator": ("string", True),
    "alpha": ("number", False),
    "lfc_shrink": ("boolean", False),
}


def _validate_relative_path(value: str, *, label: str) -> str:
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if (
        not value
        or windows_path.drive
        or windows_path.root
        or "\\" in value
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"{label} must be a safe relative path")
    return value


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        copied = super().model_copy(update=update, deep=deep)
        payload = {
            field_name: getattr(copied, field_name)
            for field_name in type(self).model_fields
        }
        return type(self).model_validate(payload)


class ResourceLimits(_FrozenModel):
    timeout_seconds: int = Field(gt=0)
    memory_mb: int = Field(gt=0)


class RuntimeSpec(_FrozenModel):
    language: Literal["R"]
    r_version: str = Field(min_length=1)
    renv_lock: Path
    required_packages: tuple[str, ...] = Field(min_length=1)

    @field_validator("renv_lock")
    @classmethod
    def renv_lock_must_be_relative(cls, value: Path) -> Path:
        _validate_relative_path(value.as_posix(), label="renv_lock")
        return value


class InputSpec(_FrozenModel):
    name: Literal["counts", "metadata"]
    type: Literal["csv"]
    required: Literal[True]
    description: str = Field(min_length=1)


class ParameterSpec(_FrozenModel):
    type: Literal["string", "number", "boolean"]
    required: bool
    default: JsonValue | None = None


class _FrozenParameterMapping(Mapping[str, ParameterSpec]):
    __slots__ = ("_items",)

    def __init__(self, value: Mapping[str, ParameterSpec]) -> None:
        self._items = tuple(value.items())

    def __getitem__(self, key: str) -> ParameterSpec:
        for item_key, item_value in self._items:
            if item_key == key:
                return item_value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)


class SafetySpec(_FrozenModel):
    allow_arbitrary_code: Literal[False]
    allow_arbitrary_scripts: Literal[False]
    allow_arbitrary_path_expressions: Literal[False]


class ToolSpec(_FrozenModel):
    name: Literal["deseq2"]
    schema_version: Literal["1.0"]
    plan_schema_versions: tuple[Literal["1.0"], ...] = Field(min_length=1)
    description: str = Field(min_length=1)
    entrypoint: Path
    timeout_seconds: int = Field(gt=0)
    resource_limits: ResourceLimits
    runtime: RuntimeSpec
    inputs: tuple[InputSpec, ...] = Field(min_length=1)
    parameters: Mapping[str, ParameterSpec]
    required_artifacts: tuple[str, ...] = Field(min_length=1)
    preconditions: tuple[str, ...] = Field(min_length=1)
    postconditions: tuple[str, ...] = Field(min_length=1)
    safety: SafetySpec

    @field_validator("entrypoint")
    @classmethod
    def entrypoint_must_be_relative(cls, value: Path) -> Path:
        _validate_relative_path(value.as_posix(), label="entrypoint")
        return value

    @field_validator("required_artifacts")
    @classmethod
    def artifacts_must_be_safe_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_artifact_relative_path(value)
        if len(set(values)) != len(values):
            raise ValueError("required_artifacts must be unique")
        return values

    @field_validator("parameters")
    @classmethod
    def parameters_must_be_immutable(
        cls,
        value: Mapping[str, ParameterSpec],
    ) -> Mapping[str, ParameterSpec]:
        return _FrozenParameterMapping(value)

    @field_serializer("parameters")
    def serialize_parameters(
        self,
        value: Mapping[str, ParameterSpec],
    ) -> dict[str, ParameterSpec]:
        return dict(value)

    @model_validator(mode="after")
    def timeouts_must_agree(self) -> Self:
        if self.timeout_seconds != self.resource_limits.timeout_seconds:
            raise ValueError("timeout_seconds must match resource_limits.timeout_seconds")
        if len(self.inputs) != 2 or {item.name for item in self.inputs} != {
            "counts",
            "metadata",
        }:
            raise ValueError("inputs must declare counts and metadata exactly once")
        if set(self.parameters) != set(_EXPECTED_PARAMETERS):
            raise ValueError("parameters must match the fixed DESeq2 parameter contract")
        for name, (parameter_type, required) in _EXPECTED_PARAMETERS.items():
            parameter = self.parameters[name]
            if parameter.type != parameter_type or parameter.required is not required:
                raise ValueError("parameters must match the fixed DESeq2 parameter contract")
        return self

    def resolve_artifact(self, output_root: Path, relative_path: str) -> Path:
        if relative_path not in self.required_artifacts:
            raise ValueError(f"artifact is not declared: {relative_path}")
        root = output_root.resolve()
        parts = validate_artifact_relative_path(relative_path)
        resolved = root.joinpath(*parts).resolve()
        if root not in resolved.parents:
            raise ValueError("artifact resolves outside output root")
        return resolved


class ToolRegistry:
    def __init__(self, project_root: Path, specs_dir: Path | None = None) -> None:
        self._project_root = project_root.resolve()
        source_dir = (
            specs_dir.resolve()
            if specs_dir is not None
            else self._project_root / "tool_specs"
        )
        spec_path = source_dir / "deseq2.yaml"
        payload: object = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        self._tools = {"deseq2": ToolSpec.model_validate(payload)}
        self._validate_entrypoint(self._tools["deseq2"])

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"tool is not registered: {name}") from error

    def _validate_entrypoint(self, spec: ToolSpec) -> None:
        entrypoint = (self._project_root / spec.entrypoint).resolve()
        if self._project_root not in entrypoint.parents:
            raise ValueError("entrypoint resolves outside project root")
        if not entrypoint.is_file():
            raise FileNotFoundError(f"tool entrypoint not found: {spec.entrypoint.as_posix()}")
