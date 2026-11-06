param(
    [int]$Port = 8000,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

Push-Location $root
try {
    Require-Command "node"
    Require-Command "uv"
    Require-Command "Rscript"
    Require-Command "git"
    $checkoutRoot = & git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $checkoutRoot -or
        (Resolve-Path -LiteralPath $checkoutRoot).Path -ne (Resolve-Path -LiteralPath $root).Path) {
        throw "Use a git clone checkout of Bio-Agent so analysis manifests record a real source commit."
    }
    $nodeVersion = (& node --version).Trim().TrimStart("v")
    $parts = $nodeVersion.Split(".")
    if ([int]$parts[0] -lt 22 -or ([int]$parts[0] -eq 22 -and [int]$parts[1] -lt 12)) {
        throw "Node.js 22.12 or newer is required; found $nodeVersion."
    }
    if ($Build) {
        & npm --prefix frontend run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit code $LASTEXITCODE." }
    }
    $dist = Join-Path $root "frontend\dist"
    if (-not (Test-Path -LiteralPath (Join-Path $dist "index.html") -PathType Leaf)) {
        throw "Frontend build is missing at frontend\dist. Run npm run build in frontend."
    }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        throw "Port $Port is already in use; choose another port or stop the process yourself."
    }
    # RRunner uses a separate attempt directory, outside the project's .Rprofile.
    # Resolve the restored project library in every fresh terminal, before serving.
    # Windows PowerShell can truncate a native argument at the first CRLF.
    $rCheck = @(
        'project_library <- renv::paths$library()'
        'stopifnot(dir.exists(project_library))'
        '.libPaths(c(project_library, .libPaths()))'
        'suppressPackageStartupMessages(library(DESeq2, lib.loc = project_library))'
        'suppressPackageStartupMessages(library(apeglm, lib.loc = project_library))'
        "cat('\nBIOAGENT_R_LIB=', normalizePath(project_library, mustWork = TRUE), '\n', sep = '')"
    ) -join '; '
    $rOutput = @(& Rscript -e $rCheck)
    if ($LASTEXITCODE -ne 0) {
        throw 'Project R packages are unavailable. Run Rscript -e "renv::restore(prompt = FALSE)" from this checkout first.'
    }
    $prefix = 'BIOAGENT_R_LIB='
    $paths = @($rOutput |
        Where-Object { ([string]$_).StartsWith($prefix, [StringComparison]::Ordinal) } |
        ForEach-Object { ([string]$_).Substring($prefix.Length).Trim() })
    if ($paths.Count -ne 1 -or -not $paths[0] -or
        -not (Test-Path -LiteralPath $paths[0] -PathType Container)) {
        throw "Rscript did not return a valid project R library path."
    }
    $env:R_LIBS = $paths[0]
    Write-Host "Starting Bio-Agent workbench on http://127.0.0.1:$Port"
    & uv run uvicorn bioagent.api.app:create_app --factory --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "uvicorn stopped with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
