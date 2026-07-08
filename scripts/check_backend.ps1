$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectRoot "backend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$ScriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptsDir "offline_llm_guard.ps1")
$LlmEnvironmentSnapshot = Enable-OfflineLlmChecks

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

try {
  Invoke-QualityStep "Backend pytest" {
    Push-Location $BackendDir
    try {
      & $Python -B -m pytest -q -p no:cacheprovider
      if ($LASTEXITCODE -ne 0) {
        throw "pytest failed with exit code $LASTEXITCODE"
      }
    } finally {
      Pop-Location
    }
  }

  Write-Host ""
  Write-Host "[OK] Backend quality checks passed." -ForegroundColor Green
} finally {
  Restore-LlmCheckEnvironment -Snapshot $LlmEnvironmentSnapshot
}
