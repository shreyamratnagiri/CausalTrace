# Operations runbook

**Starting:** create `.env` from `.env.example`, replace both secrets, run `docker compose -f docker-compose.yml -f docker-compose.lab.yml up --build -d`. Migration service runs `alembic upgrade head` after Postgres readiness and before API startup. Check `/health`, `/ready`, and `docker compose ps`. The `/metrics` endpoint needs `x-api-key` because it exposes persisted telemetry counters. The Collector has no host-published port; services communicate through Compose DNS.

**Traffic:** `python scripts/load_traffic.py --requests 160 --interval 0.3` targets only the loopback lab gateway. To establish statistical baselines, spread healthy requests over at least 6 five-second windows. Run faults using `/api/lab/experiments`, not direct editing of services.

**Incident:** inspect the overview and anomaly metrics. Create an incident from evidence in the Incidents page, run Analyze to store candidates, review contradictions and trace path, then use explicit status changes. Reports are exported to JSON with timestamps and evidence; they are not independent root-cause certification.

**Retention:** run `python scripts/retention.py` with a local API and key, externally scheduled at a selected cadence. It removes older raw spans, metrics, events, and edges without deleting incident history. Backup PostgreSQL independently; there is no built-in automatic backup system.

**Recovery:** if Collector is down, its bounded retry window expires; missing telemetry cannot be reconstructed automatically. API restart preserves SQL-backed incidents, metrics and spans. A failed lab worker's fault expires within its 120s TTL even if the API dies. Examine PostgreSQL connection health, service logs, `/ready`, and Collector errors before retrying.

**Shutdown:** `docker compose -f docker-compose.yml -f docker-compose.lab.yml down`. PostgreSQL persists in named volume `pgdata`. Use `down -v` only to intentionally delete all lab evidence. HTTP timeouts are bounded (2s child dependency, 3s controls) and OTel exporter queues are bounded.

**Scale limits:** the current analysis loads the last 12,000 spans and 50,000 edges in memory per request; repeated polling is not designed for high-QPS production observability. For large deployments, precompute 5-second aggregates with bounded workers, time-partition storage, add multi-user identity and authorization, TLS, and durable buffering, and benchmark memory/backpressure before scaling.
