import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_start_script_checks_prerequisites_and_owns_no_other_processes() -> None:
    script = ROOT / "scripts" / "start-workbench.ps1"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    for required in ("node", "uv", "Rscript", "frontend\\dist", "uvicorn", "127.0.0.1"):
        assert required.lower() in text.lower()
    assert "Stop-Process" not in text and "taskkill" not in text.lower()
    assert "npm run build" in text


def run_start(
    tmp_path: Path,
    *,
    fail_r: bool = False,
    busy: bool = False,
    checkout: bool = True,
    report_library: bool = True,
):
    root = tmp_path / "clean checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "frontend" / "dist").mkdir(parents=True)
    (root / "frontend" / "dist" / "index.html").write_text("fixture")
    script = root / "scripts" / "start-workbench.ps1"
    source = (ROOT / "scripts" / "start-workbench.ps1").read_text(encoding="utf-8")
    script.write_text(source, encoding="utf-8", newline="\r\n")
    log = tmp_path / "commands.jsonl"
    wrapper = tmp_path / "invoke.ps1"
    wrapper.write_text(
        r"""
function node { $global:LASTEXITCODE = 0; 'v22.12.0' }
function git {
    $global:LASTEXITCODE = [int]$env:BIO_START_TEST_NO_CHECKOUT
    if ($global:LASTEXITCODE -eq 0) { $env:BIO_START_TEST_ROOT }
}
function Rscript {
    @{tool='Rscript'; arguments=@($args)} | ConvertTo-Json -Compress |
        Add-Content -LiteralPath $env:BIO_START_TEST_LOG
    $global:LASTEXITCODE = [int]$env:BIO_START_TEST_FAIL_R
    # Legacy PowerShell can truncate a native argument at a CRLF.
    if (($args -join ' ') -match '\r\n') {
        'renv startup'
        ''
        return
    }
    if ($env:BIO_START_TEST_REPORT_LIBRARY -eq '1') {
        "BIOAGENT_R_LIB=$env:BIO_START_TEST_LIBRARY"
    }
    'Unrelated startup output'
    ''
}
function Get-NetTCPConnection {
    if ($env:BIO_START_TEST_BUSY -eq '1') { @{LocalPort=18252} }
}
function uv {
    @{tool='uv'; arguments=@($args); r_libs=$env:R_LIBS} | ConvertTo-Json -Compress |
        Add-Content -LiteralPath $env:BIO_START_TEST_LOG
    $global:LASTEXITCODE = 0
}
try { & $env:BIO_START_TEST_SCRIPT -Port 18252; exit 0 }
catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
""",
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if key != "R_LIBS"}
    library = root / "renv" / "library with spaces"
    library.mkdir(parents=True)
    env.update(
        BIO_START_TEST_ROOT=str(root),
        BIO_START_TEST_SCRIPT=str(script),
        BIO_START_TEST_LOG=str(log),
        BIO_START_TEST_LIBRARY=str(library),
        BIO_START_TEST_FAIL_R="1" if fail_r else "0",
        BIO_START_TEST_BUSY="1" if busy else "0",
        BIO_START_TEST_NO_CHECKOUT="0" if checkout else "1",
        BIO_START_TEST_REPORT_LIBRARY="1" if report_library else "0",
    )
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    assert powershell
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, commands, env


def test_start_resolves_project_r_library_in_a_fresh_terminal(tmp_path: Path) -> None:
    result, commands, env = run_start(tmp_path)
    assert result.returncode == 0, result.stderr
    r = next(item for item in commands if item["tool"] == "Rscript")
    expression = " ".join(r["arguments"])
    assert "\r" not in expression and "\n" not in expression
    assert "renv::paths$library()" in expression
    assert "DESeq2" in expression and "apeglm" in expression
    uv = next(item for item in commands if item["tool"] == "uv")
    assert uv["r_libs"] == env["BIO_START_TEST_LIBRARY"]
    assert [str(argument) for argument in uv["arguments"][-2:]] == ["--port", "18252"]


@pytest.mark.parametrize("fail_r,busy", [(True, False), (False, True)])
def test_start_fails_before_server_when_prerequisites_fail(
    tmp_path: Path, fail_r: bool, busy: bool
) -> None:
    result, commands, _ = run_start(tmp_path, fail_r=fail_r, busy=busy)
    assert result.returncode != 0
    assert not any(item["tool"] == "uv" for item in commands)


def test_start_explains_git_checkout_requirement(tmp_path: Path) -> None:
    result, commands, _ = run_start(tmp_path, checkout=False)
    assert result.returncode != 0
    assert "git clone" in result.stderr
    assert not commands


def test_start_does_not_treat_startup_messages_as_a_library_path(tmp_path: Path) -> None:
    result, commands, _ = run_start(tmp_path, report_library=False)
    assert result.returncode != 0
    assert "R library path" in result.stderr
    assert not any(item["tool"] == "uv" for item in commands)
