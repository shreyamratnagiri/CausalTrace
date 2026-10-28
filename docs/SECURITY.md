# Security posture and threat boundaries

- Admin and ingestion writes require a constant-time-verified environment-managed API key, at least 16 characters. The web holds the key in in-memory React state only. Use a separately generated 32+ character secret and rotate it between labs.
- User input cannot pick a lab target URI. The API constructs fixed `http://{allowlisted-service}:8100/_lab/fault` endpoints, and the service checks both `CAUSALTRACE_LAB` and the matching key.
- Containers expose gateway, API and web only at `127.0.0.1`; the PostgreSQL/Redis backend network is internal. Running Compose on a machine shared with untrusted users requires additional host security.
- Request bodies are limited to 1 MiB, telemetry batches to 500, simultaneous OTLP handler slots to 8, experiment workers to 1, and fault TTL to 120s. Query output and event history are bounded. Attributes are truncated and oversized points rejected.
- Structural duplicate identifiers are constrained in the database. The API never inserts arbitrary SQL or calls user-supplied shell commands. Persisted read endpoints require the operator key by default; the environment remains a single-operator lab and not a multi-tenant application.
- Admin status transitions enforce an optimistic version and defined state machine. Audit actions are persisted in the DB. They are not tamper-evident or cryptographically signed.
- Known limitations: no multi-user OAuth/RBAC, TLS termination, distributed rate limiter, confidential-metrics redaction policy beyond attribute truncation, automated vulnerability scan execution in this environment, or verified hardened image signing. No claim of security production readiness is made.
- Artifacts contain a locally generated scikit-learn pickle: **never unpickle a model received from an untrusted party**. Inference should load only the verified build-local artifact.

Suggested commands in a networked CI environment: `python -m pip_audit`, `ruff check .`, `mypy causaltrace`, `npm audit --omit=dev`; successful execution must be observed before labeling them passed.

## Release candidate hardening

This revision requires strict OTLP trace/span ID lengths, rejects unsupported content types, bounds decoded attributes, serializes lab cancellation and activation, attempts fault cleanup even if the control request loses its acknowledgement, and refuses successful SQL pool fault shutdown while held connections may remain. Host operators still need to audit image vulnerabilities and the exposed read endpoints before remote access. The GitHub `lab-e2e.yml` workflow is **defined but not validated in this runtime**.

## Private GET routes (current revision)

On normal deployment, `CAUSALTRACE_PROTECT_READS=1` is the default. All persisted `/api/` read routes and Prometheus `/metrics` require `x-api-key` matching `CAUSALTRACE_API_KEY`. Health and readiness probes remain unauthenticated. The React dashboard's **Unlock views** control passes the key in headers; the key stays in memory only. Do not disable private reads on an externally reachable endpoint. Do not paste secrets into bug reports or logs.

**Scope:** This is one locally bound operator credential, not OAuth/OIDC, tenant identity, RBAC or TLS mutual authentication. Docker Compose deliberately binds 8000/8080/8100 only to `127.0.0.1` and fault controls are DNS allowlisted and not host-published. Security regression tests cover private reads, admin write rejection and fault allowlisting; a full dependency/vulnerability scan and Compose permission audit remain unverified.
