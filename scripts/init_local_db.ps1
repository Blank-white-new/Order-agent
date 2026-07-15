param()

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
  throw "Backend virtual environment not found: $Python"
}

if (-not $env:APP_ENV) { $env:APP_ENV = "development" }
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = "sqlite:///./.local-run/order-agent.db" }
if (-not $env:AUTO_MIGRATE_LOCAL) { $env:AUTO_MIGRATE_LOCAL = "true" }
if (-not $env:SIMULATION_DATA_ONLY) { $env:SIMULATION_DATA_ONLY = "true" }

if ($env:APP_ENV -ne "development") {
  throw "Local initialization is restricted to APP_ENV=development."
}
if (-not $env:DATABASE_URL.StartsWith("sqlite:")) {
  throw "init_local_db.ps1 only initializes local SQLite. Use explicit Alembic commands for PostgreSQL."
}
if ($env:SIMULATION_DATA_ONLY.ToLowerInvariant() -notin @("1", "true", "yes", "on")) {
  throw "Local initialization requires SIMULATION_DATA_ONLY=true."
}

New-Item -ItemType Directory -Path (Join-Path $ProjectRoot ".local-run") -Force | Out-Null
Push-Location $ProjectRoot
try {
  & $Python -B -m alembic -c backend\alembic.ini upgrade head
  if ($LASTEXITCODE -ne 0) {
    throw "Local Alembic upgrade failed with exit code $LASTEXITCODE."
  }
  & $Python -B scripts\seed_phase2_simulation_data.py
  if ($LASTEXITCODE -ne 0) {
    throw "Local migration or synthetic seed failed with exit code $LASTEXITCODE."
  }
} finally {
  Pop-Location
}

Write-Host "[OK] Phase 2 local SQLite schema and synthetic seed are ready." -ForegroundColor Green
