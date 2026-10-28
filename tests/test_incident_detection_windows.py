"""Exercise true incident-time-window semantics without a running laboratory."""
from causaltrace.api import complete_incident_detection_windows
from benchmarks.live_evaluate import evaluate_live


def test_service_alert_does_not_duplicate_incident_buckets():
    # Two observed services, only payment anomalous. One incident alert.
    rows = [
        {"service": "gateway", "start": 10},
        {"service": "payment", "start": 10},
        {"service": "gateway", "start": 15},
        {"service": "payment", "start": 15},
        {"service": "gateway", "start": 20},
        {"service": "payment", "start": 20},
    ]
    anomalies = [{"service": "payment", "start": 20}]
    windows = complete_incident_detection_windows(rows, anomalies,
                                                   19_000_000_000, 27_000_000_000)
    # [15,20) straddles start 19, [20,25) is fully exposed.
    assert len(windows) == 2
    assert windows[0]["phase"] == "baseline" and not windows[0]["alert"]
    assert windows[1]["phase"] == "fault" and windows[1]["alert"]
    assert windows[1]["alert_services"] == ["payment"]
    assert windows[1]["observed_services"] == ["gateway", "payment"]
    assert windows[1]["evaluation_unit"] == "incident_time_bucket"


def test_no_unobserved_healthy_bucket_is_invented():
    windows = complete_incident_detection_windows(
        [{"service": "gateway", "start": 20}], [], 19_000_000_000, 40_000_000_000)
    assert len(windows) == 1
    assert windows[0]["phase"] == "fault"
    assert windows[0]["alert"] is False


def test_live_scores_one_incident_bucket_per_observed_interval():
    windows = complete_incident_detection_windows(
        [{"service": "gateway", "start": 10}, {"service": "payment", "start": 10},
         {"service": "gateway", "start": 20}, {"service": "payment", "start": 20}],
        [{"service": "payment", "start": 20}], 19_000_000_000, 26_000_000_000)
    e = {"id": "real-lab-record", "mode": "error", "target": "payment", "status": "completed",
         "result": {"cleanup_verified": True, "recovery_verified": True,
                    "telemetry_provenance": "persisted OTLP spans, windowed by experiment time",
                    "ranking": ["payment"], "detection_windows": windows}}
    scored = evaluate_live([e])
    assert scored["windows_scored"] == 2
    assert scored["detection"]["precision"] == 1.0
    assert scored["detection"]["recall"] == 1.0
