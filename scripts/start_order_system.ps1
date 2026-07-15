param(
  [switch]$NoBrowser,
  [switch]$NoPauseOnError
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$ViteEntry = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"
$EnvFile = Join-Path $ProjectRoot ".env"
$RunDir = Join-Path $ProjectRoot ".codex-run"
$BackendPidFile = Join-Path $RunDir "backend.pid"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"
$BackendLog = Join-Path $RunDir "backend.log"
$BackendErrorLog = Join-Path $RunDir "backend-error.log"
$FrontendLog = Join-Path $RunDir "frontend.log"
$FrontendErrorLog = Join-Path $RunDir "frontend-error.log"
$BackendHealthUrl = "http://127.0.0.1:8000/api/health"
$VoiceStatusUrl = "http://127.0.0.1:8000/api/voice/status"
$FrontendUrl = "http://127.0.0.1:3000/"

function Get-EnvValue {
  param(
    [string]$Path,
    [string]$Name
  )

  $pattern = "^\s*{0}\s*=" -f [Regex]::Escape($Name)
  $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match $pattern } | Select-Object -Last 1
  if ($null -eq $line) {
    return $null
  }
  $value = ($line -replace $pattern, "").Trim()
  if ($value.Length -ge 2) {
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
  }
  return $value
}

function Test-TrueValue {
  param([string]$Value)
  return @("1", "true", "yes", "on") -contains (($Value + "").Trim().ToLowerInvariant())
}

function Get-PortListener {
  param([int]$Port)
  return Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Sort-Object OwningProcess -Unique |
    Select-Object -First 1
}

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

function Get-ProcessDisplayName {
  param([int]$ProcessId)
  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($null -eq $process) {
    return "unknown"
  }
  return $process.ProcessName
}

function Wait-HttpEndpoint {
  param(
    [string]$Uri,
    [string]$Name,
    [int]$TimeoutSeconds,
    [System.Diagnostics.Process]$Process
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  while ([DateTime]::UtcNow -lt $deadline) {
    if ($null -ne $Process -and $Process.HasExited) {
      throw "$Name process exited with code $($Process.ExitCode)."
    }
    try {
      $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        return
      }
    } catch {
      Start-Sleep -Milliseconds 400
    }
  }
  throw "$Name did not become ready within $TimeoutSeconds seconds: $Uri"
}

function Stop-StartedProcess {
  param(
    [System.Diagnostics.Process]$Process,
    [string]$PidFile
  )

  if ($null -ne $Process -and -not $Process.HasExited) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Process.Id)" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
      Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    $Process.WaitForExit(5000) | Out-Null
  }
  Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Write-PidFile {
  param(
    [string]$Path,
    [int]$ProcessId
  )
  Set-Content -LiteralPath $Path -Value $ProcessId -Encoding ascii
}

function Resolve-ConfiguredModelPath {
  $configured = Get-EnvValue -Path $EnvFile -Name "VOSK_MODEL_PATH"
  if ([string]::IsNullOrWhiteSpace($configured)) {
    throw "VOSK_MODEL_PATH is missing from .env."
  }
  $normalized = $configured -replace "/", "\"
  if ([IO.Path]::IsPathRooted($normalized)) {
    return [IO.Path]::GetFullPath($normalized)
  }
  return [IO.Path]::GetFullPath((Join-Path $ProjectRoot $normalized))
}

function Assert-PortAvailableOrReusable {
  param(
    [int]$Port,
    [string]$ServiceName,
    [string]$ExpectedToken
  )

  $listener = Get-PortListener -Port $Port
  if ($null -eq $listener) {
    return $null
  }
  $processId = [int]$listener.OwningProcess
  if (Test-ProjectProcess -ProcessId $processId -ExpectedToken $ExpectedToken) {
    Write-Host "$ServiceName is already running on port $Port (PID $processId); reusing it." -ForegroundColor Yellow
    return $processId
  }
  $processName = Get-ProcessDisplayName -ProcessId $processId
  throw "Port $Port is occupied by another process: PID $processId ($processName)."
}

$hashAlgorithm = [Security.Cryptography.SHA256]::Create()
try {
  $rootBytes = [Text.Encoding]::UTF8.GetBytes($ProjectRoot.ToLowerInvariant())
  $rootHash = [BitConverter]::ToString($hashAlgorithm.ComputeHash($rootBytes)).Replace("-", "").Substring(0, 16)
} finally {
  $hashAlgorithm.Dispose()
}
$mutex = New-Object System.Threading.Mutex($false, "Local\OrderSystemLauncher_$rootHash")
$mutexOwned = $false
try {
  try {
    $mutexOwned = $mutex.WaitOne(0)
  } catch [Threading.AbandonedMutexException] {
    $mutexOwned = $true
  }
  if (-not $mutexOwned) {
    Write-Host "订餐系统的另一个启动流程正在运行，请稍候。" -ForegroundColor Yellow
    exit 0
  }

  $startedBackend = $null
  $startedFrontend = $null
  $exitCode = 0
  try {
    Write-Host "正在启动订餐系统..." -ForegroundColor Cyan
    Write-Host "项目目录：$ProjectRoot"

    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
      throw "后端虚拟环境缺失。请运行：cd `"$BackendDir`"; python -m venv .venv; .\.venv\Scripts\python.exe -m pip install `"pip==26.1.2`"; .\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt"
    }
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
      throw "缺少 .env。请先从 .env.example 复制并保留本机配置。"
    }
    if (-not (Test-TrueValue (Get-EnvValue -Path $EnvFile -Name "VOICE_ENABLED"))) {
      throw "VOICE_ENABLED 必须在 .env 中设置为 true。"
    }

    $modelPath = Resolve-ConfiguredModelPath
    foreach ($requiredDirectory in @("am", "conf", "graph")) {
      $requiredPath = Join-Path $modelPath $requiredDirectory
      if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
        throw "Vosk 模型不完整，缺少目录：$requiredDirectory。请检查 VOSK_MODEL_PATH。"
      }
    }

    $nodeCommand = Get-Command node.exe -ErrorAction Stop
    $npmCommand = Get-Command npm.cmd -ErrorAction Stop
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules") -PathType Container) -or
        -not (Test-Path -LiteralPath $ViteEntry -PathType Leaf)) {
      Write-Host "前端依赖缺失，正在执行 npm ci..." -ForegroundColor Yellow
      Push-Location $FrontendDir
      try {
        & $npmCommand.Source ci
        if ($LASTEXITCODE -ne 0) {
          throw "npm ci failed with exit code $LASTEXITCODE"
        }
      } finally {
        Pop-Location
      }
    }

    New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

    $backendPid = Assert-PortAvailableOrReusable -Port 8000 -ServiceName "Backend" -ExpectedToken $PythonExe
    $frontendPid = Assert-PortAvailableOrReusable -Port 3000 -ServiceName "Frontend" -ExpectedToken $ViteEntry

    $environmentNames = @(
      "BACKEND_ENV_FILE",
      "LLM_FALLBACK_MODE",
      "LLM_FALLBACK_ENABLED",
      "LLM_FALLBACK_SPECULATIVE_ENABLED",
      "ALLOW_LIVE_LLM",
      "VITE_API_BASE_URL",
      "VITE_BACKEND_PROXY_TARGET"
    )
    $environmentSnapshot = @{}
    foreach ($name in $environmentNames) {
      $environmentSnapshot[$name] = [Environment]::GetEnvironmentVariable($name, [EnvironmentVariableTarget]::Process)
    }
    try {
      [Environment]::SetEnvironmentVariable("BACKEND_ENV_FILE", $EnvFile, [EnvironmentVariableTarget]::Process)
      [Environment]::SetEnvironmentVariable("LLM_FALLBACK_MODE", "disabled", [EnvironmentVariableTarget]::Process)
      [Environment]::SetEnvironmentVariable("LLM_FALLBACK_ENABLED", "false", [EnvironmentVariableTarget]::Process)
      [Environment]::SetEnvironmentVariable("LLM_FALLBACK_SPECULATIVE_ENABLED", "false", [EnvironmentVariableTarget]::Process)
      [Environment]::SetEnvironmentVariable("ALLOW_LIVE_LLM", "false", [EnvironmentVariableTarget]::Process)
      [Environment]::SetEnvironmentVariable("VITE_API_BASE_URL", "/api", [EnvironmentVariableTarget]::Process)
      [Environment]::SetEnvironmentVariable("VITE_BACKEND_PROXY_TARGET", "http://127.0.0.1:8000", [EnvironmentVariableTarget]::Process)

      if ($null -eq $backendPid) {
        Remove-Item -LiteralPath $BackendLog, $BackendErrorLog -Force -ErrorAction SilentlyContinue
        $startedBackend = Start-Process -FilePath $PythonExe `
          -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
          -WorkingDirectory $BackendDir `
          -RedirectStandardOutput $BackendLog `
          -RedirectStandardError $BackendErrorLog `
          -WindowStyle Hidden `
          -PassThru
        $backendPid = $startedBackend.Id
      }
      Write-PidFile -Path $BackendPidFile -ProcessId $backendPid

      Wait-HttpEndpoint -Uri $BackendHealthUrl -Name "Backend" -TimeoutSeconds 60 -Process $startedBackend
      $backendListener = Get-PortListener -Port 8000
      if ($null -eq $backendListener -or -not (Test-ProjectProcess -ProcessId $backendListener.OwningProcess -ExpectedToken $PythonExe)) {
        throw "Backend health check passed, but port 8000 is not owned by this project."
      }
      $backendPid = [int]$backendListener.OwningProcess
      Write-PidFile -Path $BackendPidFile -ProcessId $backendPid
      $voiceStatus = Invoke-RestMethod -Uri $VoiceStatusUrl -TimeoutSec 5
      if (-not $voiceStatus.canRecord -or -not $voiceStatus.asrReady) {
        throw "后端已启动，但语音服务未就绪：$($voiceStatus.disabledReason) $($voiceStatus.asrDisabledReason)"
      }

      if ($null -eq $frontendPid) {
        Remove-Item -LiteralPath $FrontendLog, $FrontendErrorLog -Force -ErrorAction SilentlyContinue
        $quotedViteEntry = '"{0}"' -f $ViteEntry
        $startedFrontend = Start-Process -FilePath $nodeCommand.Source `
          -ArgumentList @($quotedViteEntry, "--host", "127.0.0.1", "--port", "3000", "--strictPort") `
          -WorkingDirectory $FrontendDir `
          -RedirectStandardOutput $FrontendLog `
          -RedirectStandardError $FrontendErrorLog `
          -WindowStyle Hidden `
          -PassThru
        $frontendPid = $startedFrontend.Id
      }
      Write-PidFile -Path $FrontendPidFile -ProcessId $frontendPid
    } finally {
      foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $environmentSnapshot[$name], [EnvironmentVariableTarget]::Process)
      }
    }

    Wait-HttpEndpoint -Uri $FrontendUrl -Name "Frontend" -TimeoutSeconds 60 -Process $startedFrontend
    $frontendListener = Get-PortListener -Port 3000
    if ($null -eq $frontendListener -or -not (Test-ProjectProcess -ProcessId $frontendListener.OwningProcess -ExpectedToken $ViteEntry)) {
      throw "Frontend health check passed, but port 3000 is not owned by this project."
    }
    $frontendPid = [int]$frontendListener.OwningProcess
    Write-PidFile -Path $FrontendPidFile -ProcessId $frontendPid

    if (-not $NoBrowser) {
      Start-Process $FrontendUrl | Out-Null
    }

    Write-Host ""
    Write-Host "订餐系统已启动" -ForegroundColor Green
    Write-Host "前端：http://127.0.0.1:3000/"
    Write-Host "后端：http://127.0.0.1:8000/api"
    Write-Host "语音服务：ready"
    Write-Host "运行日志：$RunDir"
  } catch {
    $exitCode = 1
    Stop-StartedProcess -Process $startedFrontend -PidFile $FrontendPidFile
    Stop-StartedProcess -Process $startedBackend -PidFile $BackendPidFile
    Write-Host ""
    Write-Host "订餐系统启动失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "后端日志：$BackendLog / $BackendErrorLog"
    Write-Host "前端日志：$FrontendLog / $FrontendErrorLog"
    if (-not $NoPauseOnError) {
      Read-Host "按 Enter 键关闭窗口"
    }
  }
} finally {
  if ($mutexOwned) {
    try { $mutex.ReleaseMutex() } catch { }
  }
  $mutex.Dispose()
}

exit $exitCode
