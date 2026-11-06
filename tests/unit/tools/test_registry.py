from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bioagent.tools.registry import ToolRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = PROJECT_ROOT / "tool_specs" / "deseq2.yaml"


def _write_spec(specs_dir: Path, **updates: object) -> None:
    payload = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    payload.update(updates)
    (specs_dir / "deseq2.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_registry_loads_frozen_versioned_deseq2_spec() -> None:
    registry = ToolRegistry(project_root=PROJECT_ROOT)

    spec = registry.get("deseq2")

    assert spec.name == "deseq2"
    assert spec.schema_version == "1.0"
    assert spec.plan_schema_versions == ("1.0",)
    assert spec.entrypoint == Path("r/deseq2/run.R")
    assert spec.timeout_seconds == 1800
    assert spec.model_dump(mode="json")["parameters"]["alpha"] == {
        "type": "number",
        "required": False,
        "default": 0.05,
    }
    with pytest.raises(ValidationError):
        spec.timeout_seconds = 1
    with pytest.raises(TypeError):
        spec.parameters["arbitrary_code"] = spec.parameters["factor"]


def test_spec_copy_revalidates_security_fields() -> None:
    spec = ToolRegistry(project_root=PROJECT_ROOT).get("deseq2")

    with pytest.raises(ValidationError, match="entrypoint"):
        spec.model_copy(update={"entrypoint": Path("../outside.R")})


def test_registry_only_exposes_registered_tool() -> None:
    registry = ToolRegistry(project_root=PROJECT_ROOT)

    with pytest.raises(KeyError, match="tool is not registered: edgeR"):
        registry.get("edgeR")


def test_registry_rejects_unknown_yaml_field(tmp_path: Path) -> None:
    _write_spec(tmp_path, unexpected=True)

    with pytest.raises(ValidationError, match="unexpected"):
        ToolRegistry(project_root=PROJECT_ROOT, specs_dir=tmp_path)


def test_registry_rejects_undeclared_parameter(tmp_path: Path) -> None:
    payload = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    payload["parameters"]["arbitrary_code"] = {"type": "string", "required": False}
    _write_spec(tmp_path, parameters=payload["parameters"])

    with pytest.raises(ValidationError, match="parameters"):
        ToolRegistry(project_root=PROJECT_ROOT, specs_dir=tmp_path)


def test_registry_rejects_duplicate_input_declarations(tmp_path: Path) -> None:
    payload = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    payload["inputs"].append(payload["inputs"][0])
    _write_spec(tmp_path, inputs=payload["inputs"])

    with pytest.raises(ValidationError, match="inputs"):
        ToolRegistry(project_root=PROJECT_ROOT, specs_dir=tmp_path)


@pytest.mark.parametrize("entrypoint", ["C:/tmp/run.R", "../run.R"])
def test_registry_rejects_unsafe_entrypoint(
    tmp_path: Path,
    entrypoint: str,
) -> None:
    _write_spec(tmp_path, entrypoint=entrypoint)

    with pytest.raises(ValidationError, match="entrypoint"):
        ToolRegistry(project_root=PROJECT_ROOT, specs_dir=tmp_path)


@pytest.mark.parametrize(
    "artifact",
    ["C:/tmp/results.csv", "../results.csv", "results/../outside.csv"],
)
def test_registry_rejects_unsafe_required_artifact(
    tmp_path: Path,
    artifact: str,
) -> None:
    _write_spec(tmp_path, required_artifacts=[artifact])

    with pytest.raises(ValidationError, match="required_artifacts"):
        ToolRegistry(project_root=PROJECT_ROOT, specs_dir=tmp_path)


def test_spec_rejects_resolution_of_undeclared_artifact(tmp_path: Path) -> None:
    spec = ToolRegistry(project_root=PROJECT_ROOT).get("deseq2")

    with pytest.raises(ValueError, match="artifact is not declared"):
        spec.resolve_artifact(tmp_path, "results/not_declared.csv")
