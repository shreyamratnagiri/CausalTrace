"""Deterministic gates for online timing and three-role fault scenarios."""
from causaltrace.analytics import rank_causes
from causaltrace.api import online_fault_alert_seen
from scripts.verify_live import SCENARIOS


def test_first_complete_bucket_must_finish_before_online_detection():
    first_fault_ns = 13_000_000_000
    # Bucket [10,15) straddles the intervention and cannot count.
    assert not online_fault_alert_seen([{"start": 10}], first_fault_ns, 23_000_000_000)
    # Bucket [15,20) is a genuine full fault bucket, but still in flight at 19s.
    assert not online_fault_alert_seen([{"start": 15}], first_fault_ns, 19_000_000_000)
    assert online_fault_alert_seen([{"start": 15}], first_fault_ns, 20_000_000_000)
    assert not online_fault_alert_seen([], first_fault_ns, 30_000_000_000)


def test_lab_acceptance_explicitly_checks_three_distinct_fault_categories():
    assert SCENARIOS == (("payment", "error"), ("cache", "latency"),
                         ("database", "db_exhaustion"))
    assert len(set(SCENARIOS)) == 3


def test_ground_truth_annotations_cannot_change_inference():
    anomalies=[{"service":"payment","start":10,"score":7.0},
               {"service":"checkout","start":11,"score":5.0}]
    graph=[{"source":"checkout","target":"payment","timestamp_ns":11_000_000_000,
            "latency_ms":10,"error":True}]
    ordinary=rank_causes(anomalies,graph)
    # A ground-truth marker must not be an input to the score formula.
    poisoned=[{**a,"ground_truth":"other-service","fault_mode":"error"} for a in anomalies]
    assert ordinary == rank_causes(poisoned,graph)
