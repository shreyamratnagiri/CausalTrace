"""Score recorded instrumented fault experiments; never consume synthetic fixtures.

Detection denominator is measured *complete* five-second telemetry windows:
healthy baseline windows are negative, fault-injection windows positive.
Ambiguous boundary buckets and lost telemetry are not silently imputed.
"""
from collections import defaultdict
import argparse
import json
from pathlib import Path
from statistics import median
from causaltrace.analytics import detection_scores, ranking_scores


def evaluate_live(experiments: list[dict]) -> dict:
    if not experiments:
        raise ValueError("No measured laboratory experiments available")
    ground_truth, rankings, true, predicted, delays = [], [], [], [], []
    groups: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    detection_groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"actual": [], "predicted": []})
    recovery_latency_ms: list[float] = []
    dropped_values = []
    for record in experiments:
        result = record.get("result") or {}
        if record.get("status") != "completed" or not result.get("cleanup_verified") or not result.get("recovery_verified"):
            raise ValueError(f"Incomplete or unverified lab experiment: {record.get('id')}")
        if result.get("telemetry_provenance") != "persisted OTLP spans, windowed by experiment time":
            raise ValueError("Cannot evaluate a non-OTLP fixture as real fault evidence")
        windows = result.get("detection_windows") or []
        if not any(w["phase"] == "baseline" for w in windows) or not any(w["phase"] == "fault" for w in windows):
            raise ValueError("Missing complete healthy/fault telemetry windows")
        category=record.get("mode", "unknown")
        for w in windows:
            if w["phase"] not in {"baseline", "fault"} or not isinstance(w["alert"], bool):
                raise ValueError("Invalid temporal detection-window evidence")
            true.append(int(w["phase"] == "fault"))
            predicted.append(int(w["alert"]))
            detection_groups[category]["actual"].append(int(w["phase"] == "fault"))
            detection_groups[category]["predicted"].append(int(w["alert"]))
        for sample in result.get("recovery", []):
            if sample.get("http_status") != 200:
                raise ValueError("Unhealthy recovery sample must not be scored as verified")
            recovery_latency_ms.append(float(sample["latency_ms"]))
        truth = record.get("target")
        rank = result.get("ranking") or []
        if not truth or not rank or len(set(rank)) != len(rank):
            raise ValueError("Missing or invalid root-cause candidate ranking")
        ground_truth.append(truth)
        rankings.append(rank)
        groups[record.get("mode", "unknown")].append((truth, rank))
        if result.get("detection_delay_seconds") is not None:
            delays.append(result["detection_delay_seconds"])
        # The Collector does not expose an exact per-experiment drop counter
        # through our current OTLP API. Never silently label absent data zero.
        if result.get("dropped_events") is not None:
            value=result["dropped_events"]
            if not isinstance(value,int) or value < 0:
                raise ValueError("Invalid reported dropped event count")
            dropped_values.append(value)
    return {
        "data_origin":"actual persisted OTLP telemetry from isolated fault laboratory",
        "independence":"fault labels used only for evaluation, never inference",
        "incidents":len(experiments), "windows_scored":len(true),
        "detection":{**detection_scores(true,predicted),
                     "delays_seconds":delays,
                     "mean_detection_delay_seconds":sum(delays)/len(delays) if delays else None,
                     "missed_detection_incidents":len(experiments)-len(delays)},
        "root_cause":ranking_scores(ground_truth, rankings),
        "by_fault_category":{mode:{"root_cause":ranking_scores([t for t,_ in entries],[r for _,r in entries]),
                                   "detection":detection_scores(detection_groups[mode]["actual"],
                                                                 detection_groups[mode]["predicted"])}
                            for mode,entries in sorted(groups.items())},
        "recovery":{"verified_incidents":len(experiments),
                    "measured_successful_requests":len(recovery_latency_ms),
                    "median_latency_ms":median(recovery_latency_ms) if recovery_latency_ms else None,
                    "p95_latency_ms":(sorted(recovery_latency_ms)[min(len(recovery_latency_ms)-1,
                                     max(0,int(.95*len(recovery_latency_ms)+.999999)-1))]
                                     if recovery_latency_ms else None)},
        "dropped_events_reported":sum(dropped_values) if len(dropped_values)==len(experiments) else None,
        "dropped_events_coverage":len(dropped_values),
        "limitation":"Window statistics exclude boundary buckets; missing exports cannot be assumed zero."
    }


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--input", default="benchmarks/results.live.local.json")
    args=parser.parse_args()
    report=json.loads(Path(args.input).read_text())
    result=evaluate_live(report.get("scenarios", []))
    print(json.dumps(result,indent=2))
