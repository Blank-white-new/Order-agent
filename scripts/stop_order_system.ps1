$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$ViteEntry = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"
$RunDir = Join-Path $ProjectRoot ".codex-run"

function Get-ProcessMetadata {
  param([int]$ProcessId)
  return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
}

function Test-ProjectProcess {
  param(
    [int]$ProcessId,
    [string]$ExpectedToken
  )

  $metadata = Get-ProcessMetadata -ProcessId $ProcessId
  if ($null -eq $metadata -or [string]::IsNullOrWhiteSpace($metadata.CommandLine)) {
    return $false
  }
  return $metadata.CommandLine.IndexOf($ExpectedToken, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Stop-ProcessFromPidFile {
  param(
    [string]$ServiceName,
    [string]$PidFile,
    [string]$ExpectedToken
  )

  if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) {
    Write-Host "$ServiceName：没有 PID 文件，无需停止。" -ForegroundColor Yellow
    return
  }

  $rawPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
  $processId = 0
  if (-not [int]::TryParse($rawPid, [ref]$processId)) {
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host "$ServiceName：PID 文件无效，已清理。" -ForegroundColor Yellow
    return
  }

  $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
  if ($null -eq $process) {
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host "$ServiceName：进程已退出，已清理失效 PID。" -ForegroundColor Yellow
    return
  }

  if (-not (Test-ProjectProcess -ProcessId $processId -ExpectedToken $ExpectedToken)) {
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host "$ServiceName：PID $processId 不属于当前项目，未停止该进程；已清理失效 PID。" -ForegroundColor Yellow
    return
  }

  Stop-Process -Id $processId -Force
  try {
    Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
  } catch { }
  Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
  Write-Host "$ServiceName：已停止 PID $processId。" -ForegroundColor Green
}

function Wait-PortReleased {
  param(
    [int]$Port,
    [int]$TimeoutSeconds = 10
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  while ([DateTime]::UtcNow -lt $deadline) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($null -eq $listener) {
      return $true
    }
    Start-Sleep -Milliseconds 250
  }
  return $false
}

Write-Host "正在停止订餐系统..." -ForegroundColor Cyan
Stop-ProcessFromPidFile -ServiceName "Frontend" -PidFile (Join-Path $RunDir "frontend.pid") -ExpectedToken $ViteEntry
Stop-ProcessFromPidFile -ServiceName "Backend" -PidFile (Join-Path $RunDir "backend.pid") -ExpectedToken $PythonExe

$frontendReleased = Wait-PortReleased -Port 3000
$backendReleased = Wait-PortReleased -Port 8000
if ($frontendReleased -and $backendReleased) {
  Write-Host "订餐系统已停止，端口 3000 和 8000 已清理。" -ForegroundColor Green
  exit 0
}

if (-not $frontendReleased) {
  Write-Warning "端口 3000 仍被其他进程占用。"
}
if (-not $backendReleased) {
  Write-Warning "端口 8000 仍被其他进程占用。"
}
exit 1
