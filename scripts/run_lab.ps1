$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
foreach ($tool in @('python','npm','docker')) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing prerequisite: $tool" }
}
python scripts/bootstrap_env.py
if ($LASTEXITCODE -ne 0) { throw 'Environment bootstrap failed' }
if (-not (Test-Path 'web/package-lock.json')) {
  Write-Host 'Missing real web/package-lock.json; resolving via npm registry before Docker build'
  Push-Location web
  try {
    npm install --package-lock-only --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve genuine npm package-lock.json; verify internet/npm registry' }
  } finally { Pop-Location }
}

docker compose -f docker-compose.yml -f docker-compose.lab.yml config -q
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration invalid' }
docker compose -f docker-compose.yml -f docker-compose.lab.yml up --build -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose startup failed' }
Write-Host 'Dashboard: http://127.0.0.1:8080 | API: http://127.0.0.1:8000/ready'
