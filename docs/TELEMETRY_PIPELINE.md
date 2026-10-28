# Telemetry pipeline

1. Each sample service wraps inbound HTTP requests in `SpanKind.SERVER` spans and explicitly wraps outgoing HTTP requests in `SpanKind.CLIENT` spans; W3C propagation headers carry the parent context.
2. Python SDK `BatchSpanProcessor` exports OTLP/HTTP protobuf to Collector receiver at `collector:4318`. A periodic reader exports Counter sums over the same path.
3. Collector `memory_limiter` → `batch` → `otlphttp` exporter forwards traces and metrics to the key-protected FastAPI endpoints.
4. API rejects requests over 1 MiB by default, span batches over 500 and timestamps outside ±24 hours, and returns 429 if ingestion concurrency is saturated. Payloads are decoded as OTLP protobuf or OTLP JSON; unsupported metric types are deliberately skipped rather than invented.
5. Outbound client spans with a missing remote server span can yield `client-target-unconfirmed` edges when `server.address` is a validated service label. When the remote span arrives, the inferred edge is replaced by a directly observed parent-child edge. Atomic `ON CONFLICT DO NOTHING` on `(trace_id,span_id)` and metric fingerprint implements storage idempotency; the server reports accepted and duplicate counts. Out-of-order spans are retained and topology is reconstructed again when a parent arrives.
6. `spans` and `metrics` are indexed for recent query ranges. `/api/overview` aggregates at most 12,000 recent spans; `/api/topology` considers the 50,000 latest edges. The returned scope is documented.
7. `POST /api/admin/retention` is an explicit scheduled maintenance action; delete raw telemetry older than `RETENTION_DAYS`. Incidents and their history remain for audit until an operator manages them separately.

**Delivery semantics:** SDK output is buffered in memory; Collector retries for at most 60s and has a bounded memory queue, so some events can be lost during prolonged outages or shutdown. API writes are idempotent for supported keys. Neither end-to-end at-least-once delivery nor exactly-once processing is guaranteed. Duplicate or missing spans can arise; analytics expose orphans. There is no dead-letter queue because no durable broker is deployed.

**Limitations:** This receiver handles OTLP traces and scalar Gauge/Sum datapoints. Exponential histograms, OTLP logs, gRPC transport, and service graph inference from span links alone are not implemented. Non-finite scalar datapoints are rejected. Clock skew can compromise cross-service timing comparisons; mathematical ranking assumes clocks are reasonably synchronized.


## Ingestion hardening and metric shapes

The request middleware enforces the configured body bound while reading
chunks rather than reading an unlimited stream before checking its size.
Both OTLP endpoints and JSON ingestion use a bounded shared admission semaphore.
Common secret-bearing attribute keys are redacted; however, operators must
remove confidential data **at the instrumentation source** because a free-text
value can still contain secrets or personal information.

OTLP gauge and sum points are stored as measured scalar values. OTLP histograms
are stored as separate `.count` and `.sum` metric records. The system does **not**
report percentile values that have not been computed from a supported histogram
distribution. Span timings are independently recorded as trace evidence.
