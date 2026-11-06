param(
    [ValidateSet("All", "Python", "R")]
    [string]$Suite = "All"
)

$ErrorActionPreference = "Stop"

function Invoke-Check {
    param([string]$Program, [string[]]$Arguments)

    Write-Host ("Running: {0} {1}" -f $Program, ($Arguments -join " "))
    & $Program @Arguments
    # Windows PowerShell does not turn native nonzero exit codes into exceptions.
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit code $LASTEXITCODE"
    }
}

Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    Invoke-Check uv @("sync", "--frozen", "--dev")

    if ($Suite -in @("All", "Python")) {
        Invoke-Check uv @("run", "--no-sync", "ruff", "check", ".")
        Invoke-Check uv @("run", "--no-sync", "mypy", "src")
        Invoke-Check uv @(
            "run", "--no-sync", "pytest", "tests/unit", "tests/integration", "tests/evals",
            "-k", "not test_real_deseq2_runner_preserves_ad_vs_control_direction", "-q"
        )
    }

    if ($Suite -in @("All", "R")) {
        Invoke-Check Rscript @("-e", 'renv::restore(prompt = FALSE)')
        Invoke-Check Rscript @("-e", 'stopifnot(isTRUE(renv::status()$synchronized))')
        Invoke-Check Rscript @("r/tests/testthat.R")
        Invoke-Check uv @(
            "run", "--no-sync", "pytest",
            "tests/integration/test_deseq2_runner.py::test_real_deseq2_runner_preserves_ad_vs_control_direction",
            "tests/e2e", "-v"
        )
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    Pop-Location
}

Write-Host "All requested checks passed."
exit 0
