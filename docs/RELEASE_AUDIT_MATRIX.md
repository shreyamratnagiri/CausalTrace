# CausalTrace — Requirements / Code / Test Matrix

**Scope:** This describes the corrected source candidate, not a certified live deployment. `VERIFIED PASS` always identifies its limited test scope. Run `scripts/verify.ps1` / `.sh` on a connected Docker-capable machine. Exact observations appear in `FINAL_VALIDATION_REPORT.md`.

| Requirement | Actual source | Evidence | Release classification |
|---|---|---|---|
| Event/metric schemas and idempotency | `causaltrace/schemas.py`, `causaltrace/api.py`, `db.py` | `tests/test_api.py`, OTLP schema tests | VERIFIED PASS (SQLite/API) |
| Timestamp / ID / body limits / backpressure | `causaltrace/otlp.py`, `api.py`, `settings.py` | `test_otlp_contract_security.py`, schema/API tests | VERIFIED PASS (local tests) |
| Private telemetry/incident reads, writes and audit trail | `api.py`, `settings.py`, `db.py` | `tests/test_final_security_and_evaluation.py`, `tests/test_api.py` | VERIFIED PASS (API tests); no multi-tenant identity |
| Authentication in React dashboard | `web/src/api.ts`, `web/src/main.tsx` | Source reviewed; not browser-built | IMPLEMENTED BUT UNVERIFIED |
| OpenTelemetry SDK and OTLP HTTP spans | `causaltrace/api.py`, `otlp.py`, `scripts/smoke_otlp.py` | Executed OTLP SDK HTTP and SQLite migration smoke | VERIFIED PASS (no Collector) |
| OTLP success protobuf wire contract | `api.py` trace/metric exporters | Unit/API contract tests and SDK smoke | VERIFIED PASS (SDK), Collector unverified |
| Collector and container networking | `infra/otel/collector.yaml`, `docker-compose*.yml` | YAML parse only | IMPLEMENTED BUT UNVERIFIED |
| Real database + cache dependencies | `demo/microservices/service.py`, Compose | Single process fault smoke, not full lab | IMPLEMENTED BUT UNVERIFIED |
| W3C cross-process trace context | `scripts/smoke_distributed_*` | Executed real gateway→payment HTTP trace + persistent spans | VERIFIED PASS (2-process SQLite, not Collector) |
| Missing, duplicate, out-of-order and cyclic spans | `analytics.py`, `api.py` | `tests/test_analytics.py`, inferred edge and release regressions | VERIFIED PASS (unit/API) |
| Observed vs inferred service topology | `analytics.extract_edges`, `api.record_spans` | `tests/test_inferred_dependency_edges.py` | VERIFIED PASS (SQLite) |
| Statistical threshold and MAD anomaly baselines | `analytics.py` | `tests/test_analytics.py` | VERIFIED PASS (unit fixtures) |
| Fitted Isolation Forest model and version | `causaltrace/ml.py`, `scripts/train_ml.py`, artifacts | `tests/test_ml.py`, `benchmarks/evaluate.py` | VERIFIED PASS (synthetic only) |
| Graph-temporal ranking, contradiction, ablation | `analytics.rank_causes`, `benchmarks/evaluate.py` | Seeded 80-case regression benchmark | VERIFIED PASS (synthetic only) |
| Ground-truth separated live evaluator | `benchmarks/live_evaluate.py`, `scripts/verify_live.py` | `tests/test_final_security_and_evaluation.py` | VERIFIED PASS (scorer code), actual data unverified |
| Persistent incidents / timeline / reports | `api.py`, `db.py`, React | `tests/test_api.py` and recovery regressions | VERIFIED PASS (SQLite API), UI not built |
| Fault allowlist / TTL / controlled cancellation | `api.py`, `schemas.py`, `demo/microservices/service.py` | `test_release_regressions.py`, `test_trace_reporting_and_lab_stop.py`, `smoke_lab_service.py` | VERIFIED PASS (unit/single-role smoke) |
| Interrupted experiment reconciliation | `api.lifespan` restart reconciliation | `test_interrupted_fault_is_failed_not_marked_recovered` | VERIFIED PASS (SQLite), remote cleanup uncertain |
| Three actual fault categories + recovery | `scripts/verify_live.py`, `run_lab.py`, API worker | 3-scenario runner implemented, not executed | IMPLEMENTED BUT UNVERIFIED |
| Ten-role instrumented e-commerce checkout | `demo/microservices/service.py`, `docker-compose.lab.yml` | Not started in Docker | IMPLEMENTED BUT UNVERIFIED |
| PostgreSQL Alembic migrations | `migrations/`, `alembic.ini`, Compose migrate service | SQLite migration passed; PostgreSQL test skipped | IMPLEMENTED BUT UNVERIFIED (PostgreSQL) |
| Frontend tabs / graph / trace explorer / fault lab | `web/src/main.tsx`, `visual.tsx`, `api.ts` | Source reviewed; no npm install/build | IMPLEMENTED BUT UNVERIFIED |
| npm dependency lock | `web/package.json` | npm registry DNS EAI_AGAIN | NOT IMPLEMENTED — release blocker |
| Frontend `npm ci`, ESLint, Prettier, typecheck, Vitest, Vite, Playwright | `web/`, `.github/workflows/ci.yml` | Unavailable dependencies | IMPLEMENTED BUT UNVERIFIED; likely additional fixes required |
| Python 3.12, Ruff, mypy, vulnerability scan | `pyproject.toml`, CI config | Ran Python 3.13 pytest/compile; no Ruff/mypy/pip-audit | IMPLEMENTED BUT UNVERIFIED strict/static gates |
| HTTP + SQLite ingestion throughput and API latency | `scripts/benchmark_sqlite_smoke.py`, measured JSON | Executed 1000 accepted events, p50/p95 recorded | VERIFIED PASS (small local-only workload) |
| Collector drops, memory, storage expansion under load | tools and report field | Not measured on live stack | NOT IMPLEMENTED as measured live results |
| Docker health checks and least privilege | Compose, Dockerfiles | YAML parse, source audit | IMPLEMENTED BUT UNVERIFIED |
| CI Python / frontend / live lab checks | `.github/workflows/*.yml`, verify scripts | YAML parsed, workflow unexecuted | IMPLEMENTED BUT UNVERIFIED |
| Exact Windows/Unix developer handoff | `docs/WINDOWS_SETUP.md`, `scripts/verify.*` / `run_lab.*` | `bash -n` passed; PowerShell unexecuted | VERIFIED PASS (bash syntax); Windows host gate |

## Decision

**Release candidate pending local verification.** `web/package-lock.json` cannot be generated without npm registry connectivity, and the Docker/Collector/PostgreSQL/React full acceptance suite could not execute in this environment. A passing Python suite is insufficient to declare a 9.5/10 product. Synthetic outcomes do not establish causal validity or live incident accuracy.

## Follow-on audit, 27 October 2026 (continuation of current candidate)

| Requirement | Source implementation | Regression/verification | Current outcome |
|---|---|---|---|
| Online fault detection vs retrospective scoring | `causaltrace/api.py:online_fault_alert_seen`, `run_experiment` | `tests/test_live_release_boundaries.py` | VERIFIED PASS (unit); live Docker unverified |
| No fault-label leakage to graph ranking | `causaltrace/analytics.py:rank_causes`, separate `benchmarks/live_evaluate.py` | `tests/test_live_release_boundaries.py` | VERIFIED PASS (unit), live integration pending |
| Per-category live accuracy and recovery | `benchmarks/live_evaluate.py` | `tests/test_final_security_and_evaluation.py` | VERIFIED PASS (unit); NO LIVE METRIC YET |
| Collector health and internal access | `infra/otel/collector.yaml`, CI `lab-e2e.yml` | Internal gateway health probe in verify scripts | IMPLEMENTED BUT UNVERIFIED |
| PostgreSQL migrations and idempotent inserts | `Dockerfile.tests`, `postgres-check` Compose profile | `tests/test_postgres.py` inside private Compose network | IMPLEMENTED BUT UNVERIFIED |
| Redis readiness for ten-role lab | `docker-compose.yml`, `docker-compose.lab.yml` | Compose + full lab CI | IMPLEMENTED BUT UNVERIFIED |
| Dashboard distinguishes inferred vs observed edges | `web/src/visual.tsx` | Frontend build/Playwright | IMPLEMENTED BUT UNVERIFIED |
| Real npm lock/install/build/browser checks | `web/package.json`, `web/Dockerfile`, verification scripts | CI and PowerShell | BLOCKED: npm DNS unavailable; lockfile absent |
| Real payment, cache and DB faults | `demo/microservices/service.py`, `scripts/verify_live.py` | Full Docker acceptance job | IMPLEMENTED BUT UNVERIFIED |
| Windows/Unix reproducible one-command verification | `scripts/verify.ps1`, `scripts/verify.sh`, `scripts/run_lab.*` | `bash -n` locally; PowerShell requires Windows | PARTIAL: shell syntax pass, Windows execution unverified |
| Local algorithm/API regression | `tests/` and `causaltrace/` | `pytest -q`: 47 passed, 1 skipped | VERIFIED PASS (SQLite/unit) |

**Do not treat a config parser accepting YAML as evidence Docker Compose or
OpenTelemetry Collector accepts the configuration.** The release remains
non-certified until the blocked gates above run on a supported host.

## Final continuation: corrected source candidate, 27 October 2026

| Original requirement | Source implementation | Test/verification | Classification |
|---|---|---|---|
| Correct incident detection denominator | `causaltrace/api.py:complete_incident_detection_windows` | `tests/test_incident_detection_windows.py` | VERIFIED PASS (unit), live accuracy UNVERIFIED |
| Reject fake database exhaustion | `demo/microservices/service.py:reserve_db_connections` | `tests/test_database_fault_reservation.py` | VERIFIED PASS (negative path only), actual PG fault UNVERIFIED |
| Preserve missed RCA predictions | `scripts/verify_live.py`, `benchmarks/live_evaluate.py` | `tests/test_final_security_and_evaluation.py` | VERIFIED PASS (scorer), live RCA UNVERIFIED |
| Persist actual experimental score for dashboard | `scripts/verify_live.py`, `/api/benchmarks`, React Benchmarks tab | Host `scripts/verify_live.py` | IMPLEMENTED BUT UNVERIFIED |
| True PostgreSQL migrations/index/FK/rollback | `Dockerfile.tests`, PG Compose profile, `migrations/` | `tests/test_postgres.py`, `tests/test_postgres_integrity.py` | IMPLEMENTED BUT UNVERIFIED (3 skipped locally) |
| Chronologically correct React trend order | `web/src/api.ts`, `web/src/visual.tsx` | `web/src/visual.test.ts` | IMPLEMENTED BUT UNVERIFIED (TS syntax check only) |
| Isolated, non-destructive verification | `scripts/verify.ps1`, `.sh`, CI workflow | Bash syntax and YAML parse | VERIFIED PASS (syntax), host execution UNVERIFIED |
| Frontend reproducible dependency graph | `web/package.json`, `web/Dockerfile`, CI | npm registry unreachable | NOT IMPLEMENTED: genuine lockfile unavailable |
| Full ten-role integration, Collector, browser and three faults | Compose, lab services, `scripts/verify_live.py`, Playwright | Docker + npm required | IMPLEMENTED BUT UNVERIFIED |

Local latest suite: **52 passed, 3 skipped**, plus executed SDK OTLP, cross-process trace, single-service HTTP-fault smoke and seeded synthetic evaluation. **NOT a production release.**
