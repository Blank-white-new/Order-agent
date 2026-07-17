param(
  [switch]$Build
)

$ErrorActionPreference = "Stop"

$ScriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptsDir
$VenvPython = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
. (Join-Path $ScriptsDir "offline_llm_guard.ps1")
$LlmEnvironmentSnapshot = Enable-OfflineLlmChecks

try {
  Write-Host "Running all quality checks..." -ForegroundColor Cyan

  Write-Host ""
  Write-Host "==> Phase 1 scenario catalog" -ForegroundColor Cyan
  & $Python (Join-Path $ScriptsDir "validate_phase1_scenarios.py")
  if ($LASTEXITCODE -ne 0) {
    throw "Phase 1 scenario validation failed with exit code $LASTEXITCODE"
  }
  Write-Host "[OK] Phase 1 scenario catalog" -ForegroundColor Green

  Write-Host ""
  Write-Host "==> Phase 1 runtime safety policy" -ForegroundColor Cyan
  & $Python -B (Join-Path $ProjectRoot "evaluation\run_phase1_runtime_policy_eval.py")
  if ($LASTEXITCODE -ne 0) {
    throw "Phase 1 runtime safety policy evaluation failed with exit code $LASTEXITCODE"
  }
  Write-Host "[OK] Phase 1 runtime safety policy" -ForegroundColor Green

  Write-Host ""
  Write-Host "==> Phase 4 multilingual catalog and messages" -ForegroundColor Cyan
  & $Python (Join-Path $ScriptsDir "validate_phase4_multilingual_catalog.py")
  if ($LASTEXITCODE -ne 0) {
    throw "Phase 4 catalog validation failed with exit code $LASTEXITCODE"
  }
  Write-Host "[OK] Phase 4 multilingual catalog and messages" -ForegroundColor Green

  Write-Host ""
  Write-Host "==> Phase 4 multilingual text evaluation" -ForegroundColor Cyan
  & $Python -B (Join-Path $ProjectRoot "evaluation\run_phase4_multilingual_text_eval.py")
  if ($LASTEXITCODE -ne 0) {
    throw "Phase 4 multilingual text evaluation failed with exit code $LASTEXITCODE"
  }
  Write-Host "[OK] Phase 4 multilingual text evaluation" -ForegroundColor Green

  & (Join-Path $ScriptsDir "check_backend.ps1")
  & (Join-Path $ScriptsDir "check_frontend.ps1") -Build:$Build

  Write-Host ""
  Write-Host "[OK] All quality checks passed." -ForegroundColor Green
} finally {
  Restore-LlmCheckEnvironment -Snapshot $LlmEnvironmentSnapshot
}
