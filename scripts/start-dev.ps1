$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$BackendVenv = Join-Path $BackendDir ".venv"
$PythonExe = Join-Path $BackendVenv "Scripts\python.exe"
$PinnedPip = "26.1.2"

function Get-FreePort {
  param([int]$StartPort)

  $port = $StartPort
  while (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    $port += 1
  }
  return $port
}

Write-Host "Starting Multi-Agent Ordering System..." -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
  Write-Host "No .env file found. Backend will use safe defaults where possible." -ForegroundColor Yellow
}

if (-not (Test-Path $PythonExe)) {
  Write-Host "Creating backend virtual environment..."
  Push-Location $BackendDir
  python -m venv .venv
  Pop-Location
}

Write-Host "Installing backend dependencies..."
& $PythonExe -m pip install "pip==$PinnedPip"
& $PythonExe -m pip install -r (Join-Path $BackendDir "requirements.lock.txt")

& $PythonExe -B (Join-Path $ProjectRoot "scripts\auto_init_local_db.py")
if ($LASTEXITCODE -ne 0) {
  throw "Local database initialization failed; startup stopped."
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
  Write-Host "Installing frontend dependencies..."
  Push-Location $FrontendDir
  npm ci
  Pop-Location
}

$BackendPort = Get-FreePort 8000
$FrontendPort = Get-FreePort 3000
$FrontendApiBase = "http://localhost:$BackendPort/api"

if ($BackendPort -ne 8000) {
  Write-Host "Port 8000 is busy. Using backend port $BackendPort instead." -ForegroundColor Yellow
}
if ($FrontendPort -ne 3000) {
  Write-Host "Port 3000 is busy. Using frontend port $FrontendPort instead." -ForegroundColor Yellow
}

$BackendCommand = "Set-Location '$BackendDir'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port $BackendPort"
$FrontendCommand = "Set-Location '$FrontendDir'; `$env:VITE_API_BASE_URL='$FrontendApiBase'; npm run dev -- --host 127.0.0.1 --port $FrontendPort"

Start-Process powershell.exe -WorkingDirectory $BackendDir -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $BackendCommand)
Start-Sleep -Seconds 2
Start-Process powershell.exe -WorkingDirectory $FrontendDir -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $FrontendCommand)
Start-Sleep -Seconds 3
Start-Process "http://localhost:$FrontendPort"

Write-Host ""
Write-Host "Backend:  http://localhost:$BackendPort" -ForegroundColor Green
Write-Host "Frontend: http://localhost:$FrontendPort" -ForegroundColor Green
Write-Host "Two terminal windows were opened for the backend and frontend dev servers."
