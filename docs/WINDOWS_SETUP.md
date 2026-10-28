# Windows PowerShell — exact developer handoff

Run these commands in **PowerShell** (not Command Prompt). The required tools are Python 3.12 with pip, Node.js 22 with npm, Git, and Docker Desktop with Docker Compose v2. Start Docker Desktop and ensure its Linux container engine is running.

## Clean extraction and prerequisites

Extract `CausalTrace_Final_Local_Verification_Handoff.zip` and enter the nested `causaltrace` directory, the one containing `docker-compose.yml`:

```powershell
cd .\causaltrace
python --version
node --version
npm --version
docker --version
docker compose version
docker info
```

Any failing prerequisite must be fixed on the host before a full-stack test. Do not run the lab against production infrastructure. All published app ports should be loopback (`127.0.0.1`).

## One-command local lab startup

```powershell
python scripts/bootstrap_env.py
.\scripts\run_lab.ps1
```

`bootstrap_env.py` creates `.env` with randomly generated secrets only if the file does not exist. **Do not commit it or paste its contents into issues/logs.** `run_lab.ps1` validates Compose, builds containers, and waits for healthy services. A correctly started lab exposes:

- Dashboard: http://127.0.0.1:8080
- API readiness: http://127.0.0.1:8000/ready
- Gateway checkout (test-only payment): http://127.0.0.1:8100/checkout

Readiness and the test-only gateway are available without an operator key:

```powershell
curl.exe -f http://127.0.0.1:8000/ready
curl.exe -f http://127.0.0.1:8100/checkout
```

## Execute all available release checks

From the repository root:

```powershell
.\scripts\verify.ps1 *> local-validation.log
if (-not $?) { Get-Content .\local-validation.log -Tail 120 }
```

The script installs project dependencies, runs Python tests, Ruff, mypy, real Python SDK and two-process OTLP/HTTP smoke tests, seeded synthetic ML evaluation, resolves a **genuine registry-generated** npm lockfile if missing (commit it before pushing CI), runs npm/TypeScript/ESLint/Prettier/Vitest/Vite, launches and validates the Docker lab, runs three isolated fault experiments and recovery, checks browser-to-live-API traces, and runs HTTP performance probes. **Failures exit nonzero.** No test result is promised in advance.

If dependency installation fails due to network restrictions, check `npm config get registry`, DNS and your corporate proxy. Do not make up a package lockfile. Generate the lockfile using a connected host, then commit it:

```powershell
cd web
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
npm ci --no-audit --no-fund
cd ..
```

The provided candidate lacks a lockfile because npm registry DNS failed in the build environment. The host verification/launch scripts now automatically invoke npm to resolve a genuine lockfile when missing; a failed registry request stops the script. CI still requires the actual lockfile to be committed in Git and will fail until then. `web/package-lock.json` is required in source control for reproducible CI and `npm ci`.

**Private dashboard:** open `http://127.0.0.1:8080`, enter the `CAUSALTRACE_API_KEY` value from your local `.env` into **Operator key**, and click **Unlock views**. The key stays in memory, not localStorage or cookies.

## Logs and safe recovery

```powershell
docker compose -f docker-compose.yml -f docker-compose.lab.yml ps
docker compose -f docker-compose.yml -f docker-compose.lab.yml logs --no-color --tail=200 > docker-debug.log
Get-Content .\local-validation.log -Tail 100
Get-Content .\benchmarks\results.live.local.json -ErrorAction SilentlyContinue
```

If a fault scenario fails, do not call it complete. Faults have TTLs, but a failed cleanup or post-fault checkout must be investigated. To stop the lab **without deleting database evidence**:

```powershell
docker compose -f docker-compose.yml -f docker-compose.lab.yml down
```

Only destroy its persistent test database volume intentionally; do not use `down -v` casually. Keep `.env` and logs containing sensitive content private.

## Meaning of the results

The two-process smoke test independently verifies genuine gateway/payment HTTP trace-context propagation using a temporary SQLite database, not the production Collector. The **full** `verify_live.py` stage is separate; it validates the instrumented Compose services and stores experimental evidence in `benchmarks/results.live.local.json`. Treat the latter as measured only after the script returns successful verification with retained records.

## Isolated PostgreSQL migration verification (no host database exposure)

The release verification scripts now include a real PostgreSQL transaction test
against the migrated database *inside* the Docker backend network. To run it
independently after starting the lab:

```powershell
docker compose -f docker-compose.yml -f docker-compose.lab.yml --profile verification run --build --rm postgres-check
```

Expect `tests/test_postgres.py` to run rather than skip. This command must
exit nonzero if a migration or database transaction fails. It uses the separate
`Dockerfile.tests` image and never publishes Postgres to host networking.

## Source candidate update (27 October 2026)

The current regression suite has **52 passes, 3 PostgreSQL skips**. Two real OTel HTTP smoke tests and the isolated single-service TTL test passed. Docker/Collector/PostgreSQL full-stack and frontend build remain unverified. The verified live runner now persists a labeled `isolated_lab` benchmark record, and `verify.ps1` uses a uniquely named disposable Compose project so that its cleanup never removes your normal named database volume. See `REMAINING_LOCAL_VERIFICATION.md` and `FINAL_VALIDATION_REPORT.md` for strict gates.

This handoff adds an isolated temporary `postgres-test` database for the `postgres-check` verification profile. The test service no longer points to the application database. See `LOCAL_VERIFICATION_HANDOFF.md`.
