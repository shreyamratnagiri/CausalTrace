# Remaining host verification — strict release blockers

This source candidate is **not** certified until the items below actually run successfully on a suitable host. A CI workflow file is not evidence of CI success.

## Prerequisites and reproducible dependencies

Install Python 3.12, Node.js 22, Docker Desktop/Compose v2 and npm registry access. From `causaltrace/`, run `python scripts/bootstrap_env.py` to generate ignored `.env` secrets without overwriting existing secrets.

The archive intentionally omits `web/package-lock.json` because this environment could not reach the npm registry. Generate it **with npm** (never manually) and commit it before relying on CI:

```powershell
cd web
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
npm ci --no-audit --no-fund
npm run typecheck
npm run lint
npm run format:check
npm run test
npm run build
npx playwright install chromium
cd ..
```

Fix any authentic frontend errors found by these gates. No React build, ESLint or Playwright success is currently claimed.

## Strict end-to-end run

```powershell
# Start Docker Desktop first; run from causaltrace/
.\scripts\verify.ps1 *> local-validation.log
if (-not $?) { Get-Content local-validation.log -Tail 150 }
```

`verify.ps1` uses a disposable Compose project distinct from the normal app, destroys only its disposable volumes, and records failure logs in `benchmarks/local-verification-logs/failure.log`. It runs PostgreSQL integration tests without skipping, private Collector readiness, a genuine multi-hop checkout, payment failure, cache latency, database pool exhaustion, incident/report generation, recovery, API-backed Playwright, and performance probes. Linux/macOS equivalent: `bash scripts/verify.sh`.

To use/preserve an ordinary local instance for inspection instead, run `.\scripts\run_lab.ps1`, and stop it with `docker compose -f docker-compose.yml -f docker-compose.lab.yml down` **without `--volumes`**.

## Acceptance criteria

- Each test must return exit status zero; a skipped PostgreSQL test is not sufficient.
- `benchmarks/results.live.local.json` must contain `status: "passed"`, three completed experiment records with persisted telemetry, anomaly evidence, ranking candidates, confirmed cleanup/recovery, and measured scores (including negative results).
- The `Benchmarks` dashboard must read the persisted `isolated_lab` evaluation record; the trace explorer must display true cross-service trace IDs.
- Source-level failures discovered by strict Python/JS tooling or live Docker execution still require correction. Do not label this archive a final production release merely because source files or scripts exist.
- Report real Collector drop counters only when observed; unknown remains null.

## Diagnostics

```powershell
docker compose -f docker-compose.yml -f docker-compose.lab.yml config -q
docker compose -f docker-compose.yml -f docker-compose.lab.yml ps
docker compose -f docker-compose.yml -f docker-compose.lab.yml logs --no-color --tail=200 > docker-debug.log
Get-Content .\benchmarks\local-verification-logs\failure.log -ErrorAction SilentlyContinue
Get-Content .\benchmarks\results.live.local.json -ErrorAction SilentlyContinue
```

Keep `.env`, generated logs, raw traces and incident data private. Never use these controls against external production services.
