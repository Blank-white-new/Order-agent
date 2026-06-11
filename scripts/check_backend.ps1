$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectRoot "backend"

function Invoke-QualityStep {
  param(
    [string]$Name,
    [scriptblock]$Action
  )

  Write-Host ""
  Write-Host "==> $Name" -ForegroundColor Cyan
  try {
    & $Action
    Write-Host "[OK] $Name" -ForegroundColor Green
  } catch {
    Write-Host "[FAIL] $Name" -ForegroundColor Red
    throw
  }
}

Invoke-QualityStep "Backend pytest" {
  Push-Location $BackendDir
  try {
    python -B -m pytest -q -p no:cacheprovider
  } finally {
    Pop-Location
  }
}

Write-Host ""
Write-Host "[OK] Backend quality checks passed." -ForegroundColor Green
