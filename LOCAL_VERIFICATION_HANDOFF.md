# CausalTrace — source handoff / local acceptance

Status: **SOURCE CANDIDATE, NOT CERTIFIED**. The source has received the final CI-browser authentication and PostgreSQL isolation repairs. The ten-role Docker/Collector/PostgreSQL experiment has not run in this sandbox.

## Source-level changes in this handoff

1. `.github/workflows/lab-e2e.yml`: the browser step loads the generated `.env` in **that step's shell**, rejects an unset or empty `CAUSALTRACE_API_KEY`, exports it to Playwright, and makes a successful authenticated request to the running API before executing the live tests. No key is printed or checked in. Also moved the npm lockfile existence gate ahead of setup-node's cache initialization.
2. `web/tests/live-telemetry.spec.ts`: when live testing is requested, a missing key throws an explicit error rather than silently sending a blank API key.
3. `docker-compose.yml`: `postgres-check` now connects to `postgres-test`, a separate temporary PostgreSQL instance with ephemeral data storage and no published port; it never points at the application `pgdata` volume.
4. `Dockerfile.tests`: applies Alembic migrations to the temporary test database before running PostgreSQL test suites; migrations and tests fail the container on failure.
5. `tests/test_postgres.py`: the idempotency integration test rolls back its inserted rows and checks they do not persist.
6. `tests/test_ci_release_contract.py`: regression checks assert the protected live browser CI key wiring and separate PostgreSQL test database/migrations/rollback contract.

## Prerequisites on Windows

Install Python **3.12** with pip, Node.js **22**, npm, Docker Desktop with Linux containers/Compose v2. Ensure the npm registry is reachable. Enter the **nested** `causaltrace` root containing `docker-compose.yml`.

```powershell
python --version
node --version
npm --version
docker info
python scripts/bootstrap_env.py
# A valid lockfile can only be produced using actual npm registry metadata.
Push-Location web
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'npm lockfile resolution failed; verify DNS/registry access' }
npm ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
Pop-Location
# After verifying lockfile, commit web/package-lock.json to Git.
.\scripts\verify.ps1 *> local-validation.log
if ($LASTEXITCODE -ne 0 -or -not $?) { Get-Content .\local-validation.log -Tail 160; throw 'Release gate failed' }
```

`verify.ps1` uses a **unique disposable Compose project** and only destroys that project's volumes. `run_lab.ps1` alone uses the current Compose project and does **not** automatically remove its persistent data. Never use `docker compose down -v` in a regular data-bearing project.

### Investigating failures without disclosing secrets

```powershell
Get-Content .\local-validation.log -Tail 120
Get-Content .\benchmarks\results.live.local.json -ErrorAction SilentlyContinue
docker compose -f docker-compose.yml -f docker-compose.lab.yml ps
docker compose -f docker-compose.yml -f docker-compose.lab.yml logs --no-color --tail=100 *> docker-debug.log
```

The complete verification must run **three real faults** (`payment/error`, `cache/latency`, `database/db_exhaustion`), show actual propagated trace IDs, check anomaly/ranking evidence, export an incident report, and verify post-fault checkout recovery. Failed rankings remain measured negative results; missing telemetry/recovery fails the gate. Keep `.env`, logs, and traces confidential.

## Still unverified here

- Genuine npm lockfile, `npm ci`, strict TypeScript, ESLint, Prettier, Vitest, Vite build, Playwright runtime. npm registry DNS was unavailable and package dependencies were not cached.
- Docker Compose startup and PostgreSQL migration/transaction test on the isolated test container.
- Collector routing, Redis, the complete ten-role HTTP trace flow and three isolated live experiments.
- End-to-end live precision/recall/F1, delay, Top-1/Top-3/MRR and recovery benchmarks. Do not substitute synthetic results.

The original 52-pass/3-skip Python baseline predates this handoff. See `FINAL_VALIDATION_REPORT.md` for which checks actually executed here.
