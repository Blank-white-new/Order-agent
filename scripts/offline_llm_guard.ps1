function Enable-OfflineLlmChecks {
  $variableNames = @(
    "LLM_FALLBACK_ENABLED",
    "LLM_FALLBACK_SPECULATIVE_ENABLED",
    "LLM_FALLBACK_API_KEY",
    "LLM_FALLBACK_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "BACKEND_ENV_FILE"
  )
  $snapshot = @{}
  foreach ($name in $variableNames) {
    $snapshot[$name] = [Environment]::GetEnvironmentVariable($name, [EnvironmentVariableTarget]::Process)
  }

  [Environment]::SetEnvironmentVariable("LLM_FALLBACK_ENABLED", "false", [EnvironmentVariableTarget]::Process)
  [Environment]::SetEnvironmentVariable("LLM_FALLBACK_SPECULATIVE_ENABLED", "false", [EnvironmentVariableTarget]::Process)
  foreach ($name in @(
    "LLM_FALLBACK_API_KEY",
    "LLM_FALLBACK_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL"
  )) {
    [Environment]::SetEnvironmentVariable($name, $null, [EnvironmentVariableTarget]::Process)
  }
  $offlineEnvFile = Join-Path ([IO.Path]::GetTempPath()) ("agent-order-offline-{0}.env" -f [Guid]::NewGuid().ToString("N"))
  [Environment]::SetEnvironmentVariable("BACKEND_ENV_FILE", $offlineEnvFile, [EnvironmentVariableTarget]::Process)

  Write-Host "LLM fallback disabled for checks; live provider configuration is isolated." -ForegroundColor Yellow
  return $snapshot
}

function Restore-LlmCheckEnvironment {
  param(
    [hashtable]$Snapshot
  )

  foreach ($name in $Snapshot.Keys) {
    [Environment]::SetEnvironmentVariable($name, $Snapshot[$name], [EnvironmentVariableTarget]::Process)
  }
}
