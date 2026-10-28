# API contract

FastAPI exposes generated OpenAPI `/openapi.json` and interactive `/docs`. API key: `x-api-key: <CAUSALTRACE_API_KEY>` on writes and OTLP ingest. Reads are available in the local trusted laboratory, not safe for public exposure without an authenticating proxy.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/ready`, `/metrics` | Liveness, SQL readiness, Prometheus text |
| POST | `/v1/traces`, `/v1/metrics` | OTLP protobuf/JSON trace and supported metrics ingestion |
| POST | `/api/telemetry/events`, `/api/telemetry/metrics` | Typed custom event and scalar metric ingestion |
| GET | `/api/overview`, `/api/services`, `/api/services/{id}` | Recent telemetry and services |
| GET | `/api/topology` | Observed dependency edges with optional epoch-seconds range |
| GET | `/api/traces`, `/api/traces/{id}` | Paginated trace summary and reconstructed graph |
| GET | `/api/metrics`, `/api/anomalies?method=robust|threshold|ml` | Metrics and baseline/ML detectors |
| POST | `/api/deployments` | Record a deployment marker |
| GET/POST | `/api/incidents` | List/create persistent incidents |
| POST | `/api/incidents/detect` | Explicitly create incident from current detected signals |
| GET/PATCH | `/api/incidents/{id}` | Incident detail/status |
| GET | `/api/incidents/{id}/timeline`, `/api/incidents/{id}/root-causes` | Event history and evidence ranking |
| POST | `/api/incidents/{id}/analyze` | Persist current evidence ranking |
| GET | `/api/reports/{id}` | Evidence and history export in JSON |
| GET/POST | `/api/benchmarks` | Stored, provenance-labeled submitted evaluation records |
| GET/POST | `/api/lab/experiments` | History/start authorized local-only experiment |
| GET | `/api/lab/experiments/{id}` | Experiment status and recorded outcomes |
| POST | `/api/lab/experiments/{id}/stop` | Clear injected fault via fixed DNS allowlist |
| POST | `/api/admin/retention` | Explicit old raw telemetry cleanup |
| GET | `/api/system` | Limits, database type, lab enablement |

**Errors:** 400 malformed OTLP, 401 missing/wrong key, 403 lab disabled, 404 missing entity, 409 optimistic-state conflict, 413 oversize input, 422 schema/timestamp violations or insufficient anomaly evidence, 429 saturated OTLP/lab worker limit, 503 missing fitted model or unavailable storage.

**Contract detail:** all incoming custom events have bounded ids, service, timestamp and optional trace reference. Trace identifiers are lowercase 32 hex; span identifiers are 16 hex as dictated by OTLP proto. Idempotency keys are `(trace_id,span_id)`, custom `event_id`, and a digest of scalar metric identity. OTLP is bounded best-effort, not exactly-once.
