import subprocess
from pathlib import Path

import pytest

from bioagent.execution.r_runner import (
    RCommand,
    RExecutionCancelledError,
    RExecutionFailedError,
    RExecutionTimeoutError,
    RRunner,
)
from bioagent.tools.registry import ToolRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_r_command_is_argument_vector_without_shell() -> None:
    command = RCommand.build(
        project_root=Path.cwd(),
        rscript="Rscript",
        entrypoint=Path("r/deseq2/run.R"),
        parameters=Path("runs/id/parameters.json"),
    )

    assert command.argv[0] == "Rscript"
    assert Path(command.argv[1]).is_absolute()
    assert command.argv[1].endswith(("r\\deseq2\\run.R", "r/deseq2/run.R"))
    assert Path(command.argv[2]).is_absolute()
    assert command.argv[2].endswith(
        ("runs\\id\\parameters.json", "runs/id/parameters.json")
    )
    assert not hasattr(command, "shell_command")


def _runner_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    entrypoint = tmp_path / "r" / "deseq2" / "run.R"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("", encoding="utf-8")
    attempt_dir = tmp_path / "runs" / "run-id" / "attempts" / "attempt-id"
    attempt_dir.mkdir(parents=True)
    parameters = attempt_dir / "parameters.json"
    parameters.write_text("{}", encoding="utf-8")
    return entrypoint, attempt_dir, parameters


def _spec():  # type: ignore[no-untyped-def]
    return ToolRegistry(project_root=PROJECT_ROOT).get("deseq2")


def test_runner_invokes_subprocess_without_shell_and_writes_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint, attempt_dir, parameters = _runner_paths(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="warning\n")

    monkeypatch.setattr("bioagent.execution.r_runner.subprocess.run", fake_run)
    monkeypatch.setenv("BIOAGENT_SECRET_SENTINEL", "must-not-leak")
    runner = RRunner(project_root=tmp_path, rscript="Rscript")

    result = runner.run(
        spec=_spec().model_copy(update={"entrypoint": entrypoint.relative_to(tmp_path)}),
        attempt_dir=attempt_dir,
        parameters=parameters,
    )

    assert captured["shell"] is False
    assert captured["cwd"] == attempt_dir.resolve()
    assert captured["timeout"] == 1800
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["check"] is False
    assert "BIOAGENT_SECRET_SENTINEL" not in captured["env"]  # type: ignore[operator]
    environment = captured["env"]
    assert isinstance(environment, dict)
    for variable in ("R_ENVIRON", "R_ENVIRON_USER", "R_PROFILE", "R_PROFILE_USER"):
        startup_path = Path(environment[variable])
        assert attempt_dir.resolve() in startup_path.parents
        assert not startup_path.exists()
    assert result.returncode == 0
    assert result.stdout_log == attempt_dir / "logs" / "stdout.log"
    assert result.stderr_log == attempt_dir / "logs" / "stderr.log"
    assert result.stdout_log.read_text(encoding="utf-8") == "ok\n"
    assert result.stderr_log.read_text(encoding="utf-8") == "warning\n"


def test_runner_maps_timeout_to_stable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint, attempt_dir, parameters = _runner_paths(tmp_path)

    def time_out(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(args[0], 1800, output="partial", stderr="slow")

    monkeypatch.setattr("bioagent.execution.r_runner.subprocess.run", time_out)
    runner = RRunner(project_root=tmp_path, rscript="Rscript")

    with pytest.raises(RExecutionTimeoutError) as captured:
        runner.run(
            spec=_spec().model_copy(update={"entrypoint": entrypoint.relative_to(tmp_path)}),
            attempt_dir=attempt_dir,
            parameters=parameters,
        )

    assert captured.value.code == "R_EXECUTION_TIMEOUT"
    assert (attempt_dir / "logs" / "stdout.log").read_text(encoding="utf-8") == "partial"
    assert (attempt_dir / "logs" / "stderr.log").read_text(encoding="utf-8") == "slow"


def test_runner_maps_nonzero_exit_to_stable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint, attempt_dir, parameters = _runner_paths(tmp_path)

    def fail(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 9, stdout="", stderr="bad input")

    monkeypatch.setattr("bioagent.execution.r_runner.subprocess.run", fail)
    runner = RRunner(project_root=tmp_path, rscript="Rscript")

    with pytest.raises(RExecutionFailedError) as captured:
        runner.run(
            spec=_spec().model_copy(update={"entrypoint": entrypoint.relative_to(tmp_path)}),
            attempt_dir=attempt_dir,
            parameters=parameters,
        )

    assert captured.value.code == "R_EXECUTION_FAILED"
    assert captured.value.returncode == 9


def test_runner_maps_preflight_cancellation_to_stable_error(tmp_path: Path) -> None:
    entrypoint, attempt_dir, parameters = _runner_paths(tmp_path)
    runner = RRunner(project_root=tmp_path, rscript="Rscript")

    with pytest.raises(RExecutionCancelledError) as captured:
        runner.run(
            spec=_spec().model_copy(update={"entrypoint": entrypoint.relative_to(tmp_path)}),
            attempt_dir=attempt_dir,
            parameters=parameters,
            cancelled=lambda: True,
        )

    assert captured.value.code == "R_EXECUTION_CANCELLED"


def test_runner_rejects_parameter_file_outside_attempt(tmp_path: Path) -> None:
    entrypoint, attempt_dir, _ = _runner_paths(tmp_path)
    parameters = tmp_path / "parameters.json"
    parameters.write_text("{}", encoding="utf-8")
    runner = RRunner(project_root=tmp_path, rscript="Rscript")

    with pytest.raises(ValueError, match="parameters must be inside attempt directory"):
        runner.run(
            spec=_spec().model_copy(update={"entrypoint": entrypoint.relative_to(tmp_path)}),
            attempt_dir=attempt_dir,
            parameters=parameters,
        )


def test_runner_rejects_unapproved_extra_environment_variable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="extra environment variable is not allowed"):
        RRunner(
            project_root=tmp_path,
            rscript="Rscript",
            extra_env={"DEEPSEEK_API_KEY": "must-not-leak"},
        )
