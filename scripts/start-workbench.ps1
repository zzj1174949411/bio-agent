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
    Write-Host "Starting Bio-Agent workbench on http://127.0.0.1:$Port"
    & uv run uvicorn bioagent.api.app:create_app --factory --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "uvicorn stopped with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
