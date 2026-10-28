# Observational versus intervention-supported conclusions

**Observed anomaly**: a statistical deviation in recorded server spans; does not imply a fault.

**Correlated event**: another anomaly, dependency edge, or deployment event with temporal association; not sufficient evidence of mechanism.

**Candidate root cause**: a service ranked by a deterministic model using anomaly severity, topology, onset ordering, and nearby deployments; this is a **hypothesis**.

**Intervention-supported explanation**: an isolated test modifies one authorized service/fault parameter, records exactly what was changed, samples real checkout outcomes, re-observes telemetry, and compares the ranked hypothesis to the known injected target. Evidence applies to that specific intervention under that lab environment, not unrestricted environments.

Strong causal identification would require consistency, absence of uncontrolled confounding, sufficiently measured mediator structure, no interference from unrelated faults and controlled timing. Those assumptions are rarely all established from telemetry alone. CausalTrace does not report calibrated likelihoods or assert cause from correlation. The report field `proven_cause` remains `null` without an independently recorded experiment.

**Contradictory evidence matters.** An earlier anomalous caller conflicts with a simplistic candidate propagation story; such signals incur score penalty and are listed in API results. Clock skew and trace sampling can produce false contradictions; developers must not silently discard them.
