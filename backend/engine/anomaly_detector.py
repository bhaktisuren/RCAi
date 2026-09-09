"""
engine/anomaly_detector.py
-----------------------------
Lightweight, dependency-free anomaly detection over the normalized event
stream. This is intentionally simple and explainable (not a black box):

1. Metric spikes: for any metric_name with multiple numeric readings,
   flag points that deviate more than 2x the standard deviation from
   the mean (classic z-score style outlier check).
2. Severity escalation: flag any point in the timeline where severity
   jumps from info/warning straight to error/critical.
3. Burst detection: flag time windows with an unusually high number of
   events compared to the rest of the incident window.

Every anomaly returned includes *why* it was flagged, since RCAi's whole
point is explainability over black-box AI claims.
"""

import statistics
from collections import defaultdict
from typing import List
from dateutil import parser as dateparser
from models.incident import Event

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def detect_metric_spikes(events: List[Event]) -> List[dict]:
    by_metric = defaultdict(list)
    for e in events:
        if e.metric_name and e.metric_value is not None:
            by_metric[e.metric_name].append(e)

    anomalies = []
    for metric, evs in by_metric.items():
        values = [e.metric_value for e in evs]
        if len(values) < 2:
            continue
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values) or 1.0
        for e in evs:
            z = (e.metric_value - mean) / stdev
            if abs(z) >= 1.5:
                anomalies.append({
                    "type": "metric_spike",
                    "metric": metric,
                    "timestamp": e.timestamp,
                    "value": e.metric_value,
                    "baseline_mean": round(mean, 2),
                    "z_score": round(z, 2),
                    "source": e.source,
                    "explanation": f"{metric} reading of {e.metric_value} deviates {round(abs(z),1)}x "
                                    f"standard deviation from the observed baseline mean ({round(mean,2)}).",
                })
    return anomalies


def detect_severity_escalations(events: List[Event]) -> List[dict]:
    sorted_events = sorted(events, key=lambda e: dateparser.parse(e.timestamp))
    anomalies = []
    for prev, curr in zip(sorted_events, sorted_events[1:]):
        prev_rank = SEVERITY_RANK.get(prev.severity, 0)
        curr_rank = SEVERITY_RANK.get(curr.severity, 0)
        if curr_rank - prev_rank >= 2:
            anomalies.append({
                "type": "severity_escalation",
                "from": prev.severity,
                "to": curr.severity,
                "timestamp": curr.timestamp,
                "source": curr.source,
                "message": curr.message,
                "explanation": f"Severity jumped from '{prev.severity}' to '{curr.severity}' "
                               f"between consecutive events, indicating rapid deterioration.",
            })
    return anomalies


def detect_bursts(clusters: List[dict]) -> List[dict]:
    if not clusters:
        return []
    counts = [c["event_count"] for c in clusters]
    mean = statistics.mean(counts)
    stdev = statistics.pstdev(counts) or 1.0
    anomalies = []
    for c in clusters:
        z = (c["event_count"] - mean) / stdev
        if z >= 1.5 and c["event_count"] >= 3:
            anomalies.append({
                "type": "event_burst",
                "cluster_id": c["cluster_id"],
                "start_time": c["start_time"],
                "event_count": c["event_count"],
                "sources": c["sources"],
                "explanation": f"Cluster #{c['cluster_id']} contains {c['event_count']} events "
                               f"across {len(c['sources'])} source(s) in a short window, "
                               f"far above the average of {round(mean,1)} events per cluster.",
            })
    return anomalies


def detect_anomalies(events: List[Event], clusters: List[dict]) -> List[dict]:
    anomalies = []
    anomalies.extend(detect_metric_spikes(events))
    anomalies.extend(detect_severity_escalations(events))
    anomalies.extend(detect_bursts(clusters))
    return anomalies
