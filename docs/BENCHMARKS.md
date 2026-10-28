# Reproducibility and benchmark interpretation

The offline evaluation is an executed test on reproducible **synthetic mathematical fixtures**, not a performance guarantee for the actual microservice system.

Commands:

```bash
python scripts/train_ml.py --output artifacts/iforest.pkl
python benchmarks/evaluate.py
python benchmarks/evaluate.py --publish    # optional: marks records as synthetic_fixture
python scripts/perf_probe.py               # only after API startup, actual localhost HTTP latency
```

## Actual offline seeded fixture results

| Metric | Measured fixture result |
|---|---:|
| Isolation Forest test precision | 0.9189 |
| Isolation Forest test recall | 0.7234 |
| Isolation Forest test F1 | 0.8095 |
| Isolation Forest test false-alert rate | 0.0196 |
| Severity-only root-cause Top-1 | 0.4125 |
| Severity + graph Top-1 | 0.6375 |
| Graph + temporal Top-1 | 0.8375 |
| Full heuristic Top-1 | 0.9125 |
| Full heuristic Top-3 | 1.0000 |
| Full heuristic MRR | 0.9563 |

Isolation Forest test data are 200 deterministic rows seeded `3003`; model is fitted only on healthy seed `1001`, threshold selected using `2002`. Graph ranking fixture has 80 deterministic cases seeded `3003`, with injected hypothetical origin propagated through an explicitly defined service graph. Labels are used only to score rank results, not as rank inputs. Each candidate score depends only on generated observations, graph, and allowed deployment evidence. Synthetic fixtures can overstate real-world performance due to simplistic propagation.

**Unmeasured here:** PostgreSQL sustained ingestion throughput, Collector drop rate, production p50/p95, actual RAM use, storage growth and outage recovery, real fault detection delay, real lab Top-1/Top-3/MRR, end-to-end success under Docker Compose. Do not substitute synthetic fixture values for those measurements. `scripts/perf_probe.py` measures real local `/api/services` latency when run, but one endpoint alone is not a full systems benchmark.

The benchmark API stores labeled operator-submitted results and displays their provenance; submission does not constitute independent attestation. Negative results on new real traces should be preserved rather than omitted.

## Verified local SQLite/HTTP performance snapshot (27 October 2026)

`python scripts/benchmark_sqlite_smoke.py` was **actually executed** in this execution environment. It ran a temporary migrated SQLite-backed API over loopback HTTP and recorded **1,000 accepted events**, zero failed request batches, approximately **3,633.32 events/s**, p50 **10.13 ms** and p95 **12.94 ms** batch ingestion. Thirty `/api/services` requests measured p50 **1.93 ms** and p95 **3.82 ms**. Snapshot source: [`benchmarks/results.sqlite-smoke.measured.json`](../benchmarks/results.sqlite-smoke.measured.json), including runtime platform information and observed SQLite size. These data are **not** PostgreSQL, Collector, distributed-fault, production, or hardware-comparable benchmarks. Rerun on the destination host; results will differ.

## Subsequent local execution (27 October 2026)

The latest execution in the release-candidate environment ran the real
loopback HTTP + SQLite ingestion benchmark again. Observed results: **1,000
accepted events**, **0 failed batches**, **2,407.58 events/sec**, p50 batch
latency **15.31ms**, p95 **27.17ms**; 30 `/api/services` query samples had
p50 **2.00ms**, p95 **3.14ms**. These are transient local observations,
not measurements of a Docker Collector or PostgreSQL deployment. The snapshot
file was updated to these latest measurements.

`benchmarks/live_evaluate.py` now reports detection precision/recall/F1,
false-alert rate, online-observed detection delays (null if not observed),
Top-1/Top-3/MRR, per-fault-category detection/RCA and successful post-fault
HTTP recovery latencies. `dropped_events_reported` is `null` unless an actual
drop counter is present; no missing drop data are imputed to zero. The live
laboratory has not been executed here, so there are **no real fault accuracy
numbers** to report.
