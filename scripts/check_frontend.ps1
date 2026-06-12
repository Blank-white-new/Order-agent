param(
  [switch]$Build
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$FrontendDir = Join-Path $ProjectRoot "frontend"

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

Invoke-QualityStep "Frontend Vitest" {
  Push-Location $FrontendDir
  try {
    npm test -- --cache=false --reporter=dot
    if ($LASTEXITCODE -ne 0) {
      throw "npm test failed with exit code $LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
}

Invoke-QualityStep "Frontend TypeScript" {
  Push-Location $FrontendDir
  try {
    npm run typecheck
    if ($LASTEXITCODE -ne 0) {
      throw "npm run typecheck failed with exit code $LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
}

if ($Build) {
  Invoke-QualityStep "Frontend build" {
    Push-Location $FrontendDir
    try {
      npm run build
      if ($LASTEXITCODE -ne 0) {
        throw "npm run build failed with exit code $LASTEXITCODE"
      }
    } finally {
      Pop-Location
    }
  }
} else {
  Write-Host ""
  Write-Host "Skipping frontend build. Pass -Build to include it." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[OK] Frontend quality checks passed." -ForegroundColor Green
