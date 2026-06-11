param(
  [switch]$Build
)

$ErrorActionPreference = "Stop"

$ScriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Running all quality checks..." -ForegroundColor Cyan

& (Join-Path $ScriptsDir "check_backend.ps1")
& (Join-Path $ScriptsDir "check_frontend.ps1") -Build:$Build

Write-Host ""
Write-Host "[OK] All quality checks passed." -ForegroundColor Green
