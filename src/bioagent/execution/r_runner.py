import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from bioagent.tools.registry import ToolSpec

_MINIMAL_ENV_KEYS = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "COMMONPROGRAMW6432",
        "DRIVERDATA",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "PUBLIC",
        "R_HOME",
        "R_LIBS",
        "R_LIBS_USER",
        "R_USER",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERDOMAIN",
        "USERNAME",
        "USERPROFILE",
        "WINDIR",
    }
)
_ALLOWED_EXTRA_ENV_KEYS = frozenset(
    {
        "R_HOME",
        "R_LIBS",
        "R_LIBS_USER",
        "R_USER",
        "RENV_CONFIG_AUTOLOADER_ENABLED",
        "RENV_PATHS_CACHE",
        "RENV_PATHS_ROOT",
    }
)


def _resolve_within(root: Path, value: Path, *, label: str) -> Path:
    root = root.resolve()
    resolved = value.resolve() if value.is_absolute() else (root / value).resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"{label} must be inside project root")
    return resolved


@dataclass(frozen=True)
class RCommand:
    argv: tuple[str, ...]

    @classmethod
    def build(
        cls,
        *,
        project_root: Path,
        rscript: str,
        entrypoint: Path,
        parameters: Path,
    ) -> "RCommand":
        if not rscript or Path(rscript).name != rscript:
            raise ValueError("rscript must be an executable name without a path")
        root = project_root.resolve()
        resolved_entrypoint = _resolve_within(root, entrypoint, label="entrypoint")
        resolved_parameters = _resolve_within(root, parameters, label="parameters")
        return cls((rscript, str(resolved_entrypoint), str(resolved_parameters)))


@dataclass(frozen=True)
class RRunResult:
    command: RCommand
    returncode: int
    stdout_log: Path
    stderr_log: Path


class RRunnerError(RuntimeError):
    code: str

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class RExecutionTimeoutError(RRunnerError):
    def __init__(self, timeout_seconds: int) -> None:
        super().__init__(
            "R_EXECUTION_TIMEOUT",
            f"R process exceeded {timeout_seconds} seconds",
        )


class RExecutionCancelledError(RRunnerError):
    def __init__(self) -> None:
        super().__init__("R_EXECUTION_CANCELLED", "R execution was cancelled")


class RExecutionFailedError(RRunnerError):
    def __init__(self, returncode: int) -> None:
        super().__init__(
            "R_EXECUTION_FAILED",
            f"R process exited with status {returncode}",
        )
        self.returncode = returncode


class RExecutionStartError(RRunnerError):
    def __init__(self) -> None:
        super().__init__("R_EXECUTION_START_FAILED", "R process could not be started")


class RRunner:
    def __init__(
        self,
        *,
        project_root: Path,
        rscript: str,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self._project_root = project_root.resolve()
        self._rscript = rscript
        self._extra_env = dict(extra_env or {})
        disallowed_keys = set(self._extra_env) - _ALLOWED_EXTRA_ENV_KEYS
        if disallowed_keys:
            names = ", ".join(sorted(disallowed_keys))
            raise ValueError(f"extra environment variable is not allowed: {names}")

    def run(
        self,
        *,
        spec: ToolSpec,
        attempt_dir: Path,
        parameters: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> RRunResult:
        attempt = _resolve_within(
            self._project_root,
            attempt_dir,
            label="attempt directory",
        )
        if not attempt.is_dir():
            raise FileNotFoundError("attempt directory not found")
        parameter_path = _resolve_within(
            self._project_root,
            parameters,
            label="parameters",
        )
        if attempt not in parameter_path.parents:
            raise ValueError("parameters must be inside attempt directory")
        if not parameter_path.is_file():
            raise FileNotFoundError("parameter file not found")

        command = RCommand.build(
            project_root=self._project_root,
            rscript=self._rscript,
            entrypoint=spec.entrypoint,
            parameters=parameter_path,
        )
        if not Path(command.argv[1]).is_file():
            raise FileNotFoundError("R entrypoint not found")

        log_dir = attempt / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = log_dir / "stdout.log"
        stderr_log = log_dir / "stderr.log"

        if cancelled is not None and cancelled():
            self._write_logs(stdout_log, stderr_log, "", "")
            raise RExecutionCancelledError

        environment = {
            key: value for key, value in os.environ.items() if key.upper() in _MINIMAL_ENV_KEYS
        }
        environment.update(self._extra_env)
        disabled_startup_file = log_dir / f".r-startup-disabled-{uuid4().hex}"
        environment.update(
            {
                "R_ENVIRON": str(disabled_startup_file),
                "R_ENVIRON_USER": str(disabled_startup_file),
                "R_PROFILE": str(disabled_startup_file),
                "R_PROFILE_USER": str(disabled_startup_file),
            }
        )
        try:
            completed = subprocess.run(
                command.argv,
                shell=False,
                cwd=attempt,
                timeout=spec.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            self._write_logs(
                stdout_log,
                stderr_log,
                self._as_text(error.stdout),
                self._as_text(error.stderr),
            )
            raise RExecutionTimeoutError(spec.timeout_seconds) from error
        except OSError as error:
            self._write_logs(stdout_log, stderr_log, "", str(error))
            raise RExecutionStartError from error

        self._write_logs(stdout_log, stderr_log, completed.stdout, completed.stderr)
        if cancelled is not None and cancelled():
            raise RExecutionCancelledError
        if completed.returncode != 0:
            raise RExecutionFailedError(completed.returncode)
        return RRunResult(
            command=command,
            returncode=completed.returncode,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
        )

    @staticmethod
    def _write_logs(stdout_path: Path, stderr_path: Path, stdout: str, stderr: str) -> None:
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")

    @staticmethod
    def _as_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return value
