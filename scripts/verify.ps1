# PowerShell release checks; nonzero exit immediately fails the run.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
foreach ($tool in @('python','npm','docker')) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing prerequisite: $tool" }
}
function Invoke-Checked { param([string]$Exe,[string[]]$Arguments)
  & $Exe @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}
Invoke-Checked python @('-m','pip','install','-e','.[dev]')
Invoke-Checked python @('-m','compileall','-q','causaltrace','demo','benchmarks','scripts','tests')
Invoke-Checked python @('-m','pytest','-q')
Invoke-Checked python @('-m','ruff','check','causaltrace','benchmarks','scripts','tests','demo')
Invoke-Checked python @('-m','mypy','causaltrace/analytics.py','causaltrace/ml.py','causaltrace/schemas.py')
Invoke-Checked python @('scripts/smoke_otlp.py')
Invoke-Checked python @('scripts/smoke_distributed_http.py')
Invoke-Checked python @('-m','benchmarks.evaluate')
Push-Location web
try {
  if (-not (Test-Path 'package-lock.json')) {
    Write-Host 'Generating genuine npm lockfile from registry metadata (required before npm ci)...'
    Invoke-Checked npm @('install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund')
    if (-not (Test-Path 'package-lock.json')) { throw 'npm did not create a genuine package-lock.json' }
  }
  Invoke-Checked npm @('ci')
  foreach ($task in @('lint','format:check','typecheck','test','build')) { Invoke-Checked npm @('run',$task) }
} finally { Pop-Location }
Invoke-Checked python @('scripts/bootstrap_env.py')
Get-Content '.env' | ForEach-Object {
  if ($_ -match '^([A-Z0-9_]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
# Isolate this verification from the operator's regular Compose project.
$previousProject = $env:COMPOSE_PROJECT_NAME
$env:COMPOSE_PROJECT_NAME = "ctverify$PID"
try {
  & "$PSScriptRoot/run_lab.ps1"
  if ($LASTEXITCODE -ne 0) { throw 'Laboratory startup failed' }
  Invoke-Checked docker @('compose','-f','docker-compose.yml','-f','docker-compose.lab.yml','exec','-T','gateway','python','-c','import urllib.request; assert urllib.request.urlopen("http://collector:13133/", timeout=5).status == 200')
  Invoke-Checked docker @('compose','-f','docker-compose.yml','-f','docker-compose.lab.yml','--profile','verification','run','--build','--rm','postgres-check')
  Invoke-Checked python @('scripts/verify_live.py')
  Push-Location web
  try {
    Invoke-Checked npx @('playwright','install','chromium')
    $env:CAUSALTRACE_REQUIRE_LIVE='1'
    Invoke-Checked npm @('run','test:e2e')
  } finally {
    Remove-Item Env:CAUSALTRACE_REQUIRE_LIVE -ErrorAction SilentlyContinue
    Pop-Location
  }
  Invoke-Checked python @('scripts/benchmark_ingestion.py')
  Invoke-Checked python @('scripts/perf_probe.py')
} catch {
  New-Item -ItemType Directory -Path 'benchmarks/local-verification-logs' -Force | Out-Null
  & docker compose -f docker-compose.yml -f docker-compose.lab.yml logs --no-color --tail=300 2>&1 |
    Out-File -FilePath 'benchmarks/local-verification-logs/failure.log' -Encoding utf8
  throw
} finally {
  # Only the uniquely named disposable verification project is destroyed.
  & docker compose -f docker-compose.yml -f docker-compose.lab.yml down --volumes --remove-orphans 2>&1 | Out-Null
  if ($null -eq $previousProject) {
    Remove-Item Env:COMPOSE_PROJECT_NAME -ErrorAction SilentlyContinue
  } else { $env:COMPOSE_PROJECT_NAME = $previousProject }
}
