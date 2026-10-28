# Graph-temporal ranking algorithm (observational)

For candidate service `v`, construct a directed topology `G` where `caller → dependency`. Let `A(v)` be affected upstream caller services with their own detected anomalies, and `P(v)` be all graph ancestors of v. Let `t(v)` be the earliest anomalous window for v.

Define:

- `S(v) = min(1, max_anomaly_score(v)/10)`; anomaly severity.
- `P(v) = |A(v)| / max(1, |V|-1)`; proportion of other observed services impacted upstream.
- `L(v) = |{a in A(v): t(a) >= t(v)}| / max(1,|A(v)|)`; non-contradictory propagation ordering.
- `C(v) = |{a in A(v): t(a) < t(v)}| / max(1,|A(v)|)`; upstream anomalies preceding the candidate.
- `D(v) = 1` if a change to candidate v was recorded 0 to 300 seconds before onset, otherwise 0.

The full uncalibrated ranking score is:

\[
H(v) = 1.6 S(v) + 1.2 P(v) + 0.6 L(v) + 0.7 D(v) - 1.5 C(v)
\]

Ablations: **severity-only** = 1.6S; **graph** adds 1.2P; **temporal** adds 0.6L - 1.5C; **full** adds 0.7D. Sort descending, break ties deterministically by service name.

The implementation returns candidate service, score, positive evidence, negative evidence, affected upstream callers, onset time and explicit uncertainty disclaimer. Scores **are not probabilities**. Root-cause ranking is evaluated separately from detection using Top-1, Top-3 and mean reciprocal rank. Calibration is not reported as it has not been established.

**Limitations:** timestamps are window-granular; common-cause external factors may cause false ordering. Sibling services or fan-out can create correlated downstream effects. At low sample rates the rolling baseline is unreliable. A deployment merely adds association, not an intervention. Historical incidents are retained but are not currently used as a probabilistically calibrated prior. The graph method can underperform severity-only on unusual topologies; fixture-level ablation is not evidence of out-of-distribution performance.

## Directly observed versus inferred topology

For a server span with an inherited cross-service parent, topology edge provenance is `span-parent`. An outbound CLIENT span's `server.address` may instead identify a caller→target **attempt** when no server span has arrived; that edge is labeled `client-target-unconfirmed`. It is **not** evidence that the remote service received the request, and it is removed when a matching server span is later ingested. Any ranking using such topology is still observational.
