from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def run_checks(tmp_path: Path, *, fail_at: int = 0, suite: str = "All"):
    assert SCRIPT.is_file(), "The unified check script must exist"
    assert POWERSHELL, "PowerShell is required to verify the check script"
    clean_script = tmp_path / "project" / "scripts" / "check.ps1"
    clean_script.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT, clean_script)
    log = tmp_path / "commands.jsonl"
    wrapper = tmp_path / "invoke.ps1"
    # Replace only the external tools: execute the real PowerShell control flow.
    wrapper.write_text(
        """
$script:count = 0
function Record-Command($tool, $arguments) {
    $script:count++
    @{tool=$tool; arguments=@($arguments); cwd=(Get-Location).Path} |
        ConvertTo-Json -Compress | Add-Content -LiteralPath $env:BIO_CHECK_LOG
    $global:LASTEXITCODE = 0
    if ($script:count -eq [int]$env:BIO_CHECK_FAIL_AT) {
        $global:LASTEXITCODE = 23
    }
}
function uv {
    Record-Command 'uv' $args
    foreach ($argument in $args) {
        if ($argument -like '--basetemp=*') {
            $parent = Split-Path -Parent ($argument -replace '^--basetemp=', '')
            if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
                throw 'pytest base temp parent is missing in a fresh checkout'
            }
        }
    }
}
function Rscript { Record-Command 'Rscript' $args }
function npm { Record-Command 'npm' $args }
& $env:BIO_CHECK_SCRIPT -Suite $env:BIO_CHECK_SUITE
exit $LASTEXITCODE
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
        cwd=tmp_path,
        env={
            **os.environ,
            "BIO_CHECK_LOG": str(log),
            "BIO_CHECK_FAIL_AT": str(fail_at),
            "BIO_CHECK_SCRIPT": str(clean_script),
            "BIO_CHECK_SUITE": suite,
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, commands


def test_all_checks_run_from_project_root_in_dependency_order(tmp_path: Path) -> None:
    result, commands = run_checks(tmp_path)
    assert result.returncode == 0, result.stderr
    assert len(commands) == 14
    assert all(Path(command["cwd"]) == tmp_path / "project" for command in commands)
    arguments = [command["arguments"] for command in commands]
    assert arguments[0] == ["sync", "--frozen", "--dev"]
    assert arguments[1:6] == [
        ["--prefix", "frontend", "ci"],
        ["--prefix", "frontend", "run", "test", "--", "--run"],
        ["--prefix", "frontend", "run", "typecheck"],
        ["--prefix", "frontend", "run", "build"],
        ["--prefix", "frontend", "run", "e2e"],
    ]
    assert arguments[6] == ["run", "--no-sync", "ruff", "check", "."]
    assert arguments[7] == ["run", "--no-sync", "mypy", "src"]
    assert "tests/e2e/test_extensions_workflow.py" in arguments[8]
    assert {"tests/unit", "tests/integration", "tests/evals"} <= set(arguments[9])
    assert "not test_real_deseq2_runner_preserves_ad_vs_control_direction" in arguments[9]
    assert commands[10]["tool"] == "Rscript"
    assert "renv::restore(prompt = FALSE)" in arguments[10][-1]
    assert commands[11]["tool"] == "Rscript"
    assert "stopifnot" in arguments[11][-1] and "renv::status" in arguments[11][-1]
    assert arguments[12] == ["r/tests/testthat.R"]
    assert "tests/e2e" in arguments[13]
    assert any("::test_real_deseq2_runner" in argument for argument in arguments[13])


@pytest.mark.parametrize("fail_at", range(1, 15))
def test_native_failure_stops_all_subsequent_checks(tmp_path: Path, fail_at: int) -> None:
    result, commands = run_checks(tmp_path, fail_at=fail_at)
    assert result.returncode != 0
    assert len(commands) == fail_at
    assert "23" in result.stdout + result.stderr


@pytest.mark.parametrize(("suite", "count"), [("Python", 5), ("R", 5)])
def test_ci_suites_select_only_their_checks(tmp_path: Path, suite: str, count: int) -> None:
    result, commands = run_checks(tmp_path, suite=suite)
    assert result.returncode == 0, result.stderr
    assert len(commands) == count
    if suite == "Python":
        assert all(command["tool"] == "uv" for command in commands)
        assert "tests/e2e/test_extensions_workflow.py" in commands[3]["arguments"]
        assert "tests/e2e" not in commands[4]["arguments"]
    else:
        assert [command["tool"] for command in commands] == [
            "uv",
            "Rscript",
            "Rscript",
            "Rscript",
            "uv",
        ]


def test_ci_uses_both_platforms_locked_caches_and_no_secrets() -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    assert path.is_file(), "CI workflow must exist"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert "secrets." not in text.lower()
    assert "pull_request_target" not in text
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    frontend = jobs["frontend"]
    assert frontend["runs-on"] == "ubuntu-24.04"
    setup_node = next(
        step for step in frontend["steps"] if "actions/setup-node@" in step.get("uses", "")
    )
    assert setup_node["with"]["node-version"] == "22.12.0"
    assert any("npm run e2e" in step.get("run", "") for step in frontend["steps"])
    assert any("playwright install" in step.get("run", "") for step in frontend["steps"])
    assert set(jobs["python"]["strategy"]["matrix"]["os"]) == {
        "windows-latest",
        "ubuntu-24.04",
    }
    assert jobs["r-e2e"]["runs-on"] == "ubuntu-24.04"
    for name, suite in [("python", "Python"), ("r-e2e", "R")]:
        steps = jobs[name]["steps"]
        uv = next(step for step in steps if "astral-sh/setup-uv@" in step.get("uses", ""))
        assert uv["with"]["python-version"] == "3.12"
        assert uv["with"]["cache-dependency-glob"] == "uv.lock"
        assert any(f"./scripts/check.ps1 -Suite {suite}" == step.get("run") for step in steps)
    assert "hashFiles('renv.lock')" in text
    assert any("setup-renv@" in step.get("uses", "") for step in jobs["r-e2e"]["steps"])
    # Locked fs 2.1.0 requires the system libuv headers on Ubuntu.
    assert any(
        "apt-get install" in step.get("run", "") and "libuv1-dev" in step["run"]
        for step in jobs["r-e2e"]["steps"]
    )
    # RRunner starts in an attempt directory, outside the project's .Rprofile.
    assert any(
        "R_LIBS=" in step.get("run", "") and "GITHUB_ENV" in step["run"]
        for step in jobs["r-e2e"]["steps"]
    )


def test_precommit_pins_checks_without_automatic_lint_fixes() -> None:
    path = ROOT / ".pre-commit-config.yaml"
    assert path.is_file(), "pre-commit configuration must exist"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    hooks = {}
    for repo in config["repos"]:
        assert repo["rev"].startswith("v") and repo["rev"][-1].isdigit()
        hooks.update({hook["id"]: hook for hook in repo["hooks"]})
    required = {"ruff-check", "check-yaml", "check-merge-conflict", "detect-private-key"}
    assert required <= hooks.keys()
    assert "--fix" not in hooks["ruff-check"].get("args", [])


def test_bioconductor_lock_records_use_the_canonical_repository() -> None:
    lock = json.loads((ROOT / "renv.lock").read_text(encoding="utf-8"))
    records = [
        record for record in lock["Packages"].values() if record.get("Source") == "Bioconductor"
    ]
    assert records
    for record in records:
        assert record["Repository"] == f"Bioconductor {lock['Bioconductor']['Version']}"


def test_renv_bootstrap_is_recorded_in_lockfile() -> None:
    bootstrap = (ROOT / "renv" / "activate.R").read_text(encoding="utf-8")
    version = re.search(r'version <- "([^"]+)"', bootstrap)
    assert version is not None
    packages = json.loads((ROOT / "renv.lock").read_text(encoding="utf-8"))["Packages"]
    assert "renv" in packages, "The environment manager itself must be reproducible"
    assert packages["renv"]["Version"] == version.group(1)
