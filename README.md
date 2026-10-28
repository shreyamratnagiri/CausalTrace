# CausalTrace

A distributed telemetry collection and **evidence-based incident investigation** system for an isolated e-commerce application. It includes real OTLP/protobuf trace/metric ingestion, SQLAlchemy persistence, trace reconstruction, service dependency graphs, robust statistical detection, a fitted Isolation Forest comparator, graph-temporal root-cause hypotheses, persistent incident management, an administrative fault-injection laboratory, and a React operations console.

**Verification status:** See [FINAL_VALIDATION_REPORT.md](FINAL_VALIDATION_REPORT.md) and [REMAINING_LOCAL_VERIFICATION.md](REMAINING_LOCAL_VERIFICATION.md). Do not interpret presence of a Docker Compose file as proof that the complete Docker scenario was executed. Current model evaluations use separate seeded **synthetic fixtures**, not real fault-injection ground truth.

## What the product actually does

- Consumes OTLP/HTTP trace, gauge/sum metrics, and exact histogram count/sum protobufs (Collector forwards to `/v1/traces` and `/v1/metrics`). Other OTLP metric instruments, logs, and gRPC OTLP ingestion are outside the implemented support boundary.
- Persists spans, metrics, structured events, causal **candidate** rankings, incidents, timelines, experiments, and benchmark records in PostgreSQL; supports SQLite exclusively for lightweight local tests.
- Reconstructs parent/child traces including missing parents and out-of-order arrivals, flags capped results, and adds observed caller → callee edges when server spans are present. When only a client-side outbound span exists, any tentative dependency is explicitly labeled **unconfirmed**, then superseded if the remote server span later arrives.
- Detects anomalous error-rate, latency, and throughput windows from stored server spans using rolling median/MAD; also exposes an SLO threshold baseline and a separately labeled seeded Isolation Forest comparator.
- Offers an explicit local-only lab with instrumented gateway, auth, catalog, inventory, cart, checkout, payment, notification, database, and cache services. It uses genuine HTTP calls, PostgreSQL `SELECT 1`, Redis PING, and W3C trace-context propagation.
- Displays backed-by-API overview, service health, time-series, graph, traces, metrics, anomalies, incident hypotheses, event history, experiment controls, benchmark records, and JSON report exports.

## Requirements

Docker Compose v2 and Docker Engine for the full lab; or Python **3.12**, PostgreSQL, and Node **22** for development. The Python implementation also runs on Python 3.13 where compatible packages are installed.

## Docker Compose lab

```bash
cp .env.example .env
# EDIT .env: replace the example CAUSALTRACE_API_KEY and DB_PASSWORD with secrets.
docker compose -f docker-compose.yml -f docker-compose.lab.yml up --build -d
# Verify startup:
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:8100/checkout
# Generate repeated real requests with a bounded rate:
python scripts/load_traffic.py --requests 160 --interval 0.3
# Run three fault experiments; requires the secret from .env in the shell:
python scripts/run_lab.py
```

Dashboard: **http://127.0.0.1:8080**. API schema: **http://127.0.0.1:8000/docs**. The web **System** tab accepts the administrative key in memory for incident and lab operations. After entering it, switch to **Lab** or **Incidents**. All externally bound Compose ports are on 127.0.0.1. Use `docker compose -f docker-compose.yml -f docker-compose.lab.yml down` to stop. **Never use `down -v` unless discarding persisted Postgres data is intended.**

See [docs/OPERATIONS.md](docs/OPERATIONS.md) and [docs/FAULT_INJECTION.md](docs/FAULT_INJECTION.md) for safety and fault TTLs. This is an *isolated local lab*, not a managed production observability service.

## Native API/analysis development

```bash
python -m pip install -e '.[dev]'
export CAUSALTRACE_API_KEY='generate-an-independent-32-character-secret'
export DATABASE_URL='sqlite:///./causaltrace.db' # local-only test mode
alembic upgrade head
uvicorn causaltrace.api:app --host 127.0.0.1 --port 8000
# separate shell:
cd web && npm ci && npm run dev # requires real committed package-lock.json
```

For real PostgreSQL, use `postgresql+psycopg://user:password@host:5432/database` as `DATABASE_URL`; apply `alembic upgrade head` before starting the API. Do not mount SQLite onto a network filesystem or deploy it for multiworker ingestion.

## Verified local exercises

```bash
pytest -q
python scripts/smoke_otlp.py    # real OTel SDK → loopback API → SQLite + Alembic
python scripts/smoke_distributed_http.py  # two actual HTTP service processes, propagated trace
python scripts/benchmark_sqlite_smoke.py  # ephemeral measured SQLite/HTTP only, not PostgreSQL
python -m scripts.train_ml --output artifacts/iforest.pkl
python -m benchmarks.evaluate
python scripts/perf_probe.py    # requires running localhost API
```

`benchmarks/results.synthetic.json` contains only seeded fixture measurements. To make that labeled fixture visible in the benchmark dashboard, run `python -m benchmarks.evaluate --publish` against a running local API with the key exported. It will be labeled **synthetic_fixture**, never "measured lab".

## Documentation

[Windows PowerShell setup](docs/WINDOWS_SETUP.md) · [Architecture](docs/ARCHITECTURE.md) · [Telemetry](docs/TELEMETRY_PIPELINE.md) · [ML methodology](docs/ML_METHODOLOGY.md) · [Root-cause formulation](docs/ROOT_CAUSE_ALGORITHM.md) · [Causal assumptions](docs/CAUSAL_ASSUMPTIONS.md) · [Fault injection](docs/FAULT_INJECTION.md) · [Benchmarks](docs/BENCHMARKS.md) · [Security](docs/SECURITY.md) · [Operations](docs/OPERATIONS.md) · [Design decisions](docs/DESIGN_DECISIONS.md) · [API](docs/API.md)

## Evidence categories

**Anomaly** = observed metric deviation. **Correlation** = time/graph association. **Candidate root cause** = algorithmically ranked explanation. **Intervention-supported** = a fault-injection experiment independently records the manipulated component, error outcome and ranked match. None of those alone justify stating the true root cause of an arbitrary real-world incident.

## Known restrictions

Do not connect this lab to production networks. Private telemetry and incident-read APIs require the configured operator key by default; writes require the same key. This is still a local single-user design, **not** full per-user RBAC/OIDC or production TLS. Alerting currently computes over a bounded recent span subset on reads and does not automatically run as a production background detection service. No Kafka or GNN has been introduced without evidence of necessity. See the release report for unverified end-to-end acceptance.

Licensed under [MIT](LICENSE).

## Windows PowerShell and Unix handoff (requires Docker for live acceptance)

For a developer host with Python 3.12, Node 22, Docker Engine and Compose v2. The repository is a **release candidate pending live full-stack verification**, not an independently certified release:

```powershell
# Windows PowerShell: from the repository root
python scripts/bootstrap_env.py
.\scripts\run_lab.ps1
# To execute automated code/ML/UI/live acceptance and capture failure logs:
.\scripts\verify.ps1 *> local-validation.log
```

```bash
# Linux/macOS: from the repository root
bash scripts/run_lab.sh
bash scripts/verify.sh 2>&1 | tee local-validation.log
```

These verification entrypoints install project dependencies, execute available checks,
and run three real injection scenarios. If `web/package-lock.json` is absent, they
obtain **real npm registry metadata** to generate it before `npm ci`; commit the
generated lockfile before calling a release reproducible. The development sandbox
used for the latest archive could not reach npm registry or launch Docker, so it
cannot attest to the full-stack build or complete live acceptance. No such pass
is asserted in `FINAL_VALIDATION_REPORT.md`.

`python scripts/verify_live.py` writes `benchmarks/results.live.local.json`
only after the stack is running and `CAUSALTRACE_API_KEY` is exported into the
local shell. `python scripts/benchmark_ingestion.py` records actual HTTP
batch throughput into `benchmarks/results.ingestion.local.json` (never fabricated).
Both outputs are ignored by git because they are environment-dependent measurements.
See [Release audit matrix](docs/RELEASE_AUDIT_MATRIX.md).


## Current release candidate status

This revision has **43 passing Python tests, 1 skipped PostgreSQL integration test**, working local OTLP SDK and actual gateway/payment HTTP propagation smokes, and measured SQLite/loopback ingestion. The complete ten-role Docker/Collector/PostgreSQL lab has **not** been run here. npm registry DNS is unavailable and `web/package-lock.json` is missing; frontend build and Playwright checks have **not** been verified. See `FINAL_VALIDATION_REPORT.md` for exact evidence and PowerShell commands.

The API now protects all persisted `/api/` GETs and `/metrics` by default. Enter the API key in the dashboard and choose **Unlock views**. Health/readiness are exposed only on bound loopback ports. This is not multi-tenant production authentication.
