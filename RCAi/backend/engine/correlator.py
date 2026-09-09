"""
engine/correlator.py
----------------------
Takes the merged, normalized event list from all connectors and groups
events that happened close together in time into "clusters". This is the
first step of turning a firehose of alerts into a coherent timeline -
events across CloudWatch, Site24x7 and app logs that occurred within the
same short window are very likely related to the same underlying issue.
"""

from datetime import datetime
from typing import List
from dateutil import parser as dateparser
from models.incident import Event

DEFAULT_WINDOW_SECONDS = 120  # events within 2 minutes of each other cluster together


def _parse_ts(ts: str) -> datetime:
    try:
        return dateparser.parse(ts)
    except Exception:
        return datetime.utcnow()


def sort_events(events: List[Event]) -> List[Event]:
    return sorted(events, key=lambda e: _parse_ts(e.timestamp))


def correlate(events: List[Event], window_seconds: int = DEFAULT_WINDOW_SECONDS) -> List[dict]:
    """
    Groups events into clusters where each cluster's events are all within
    `window_seconds` of the previous event in the cluster (chained window).
    Returns a list of cluster dicts:
        {
          "cluster_id": int,
          "start_time": iso str,
          "end_time": iso str,
          "sources": [...],
          "max_severity": "critical",
          "event_count": int,
          "events": [Event.to_dict(), ...]
        }
    """
    if not events:
        return []

    sorted_events = sort_events(events)
    severity_rank = {"info": 0, "warning": 1, "error": 2, "critical": 3}

    clusters = []
    current_cluster = [sorted_events[0]]

    for prev, curr in zip(sorted_events, sorted_events[1:]):
        gap = (_parse_ts(curr.timestamp) - _parse_ts(prev.timestamp)).total_seconds()
        if gap <= window_seconds:
            current_cluster.append(curr)
        else:
            clusters.append(current_cluster)
            current_cluster = [curr]
    clusters.append(current_cluster)

    result = []
    for i, cluster in enumerate(clusters, start=1):
        sources = sorted(set(e.source for e in cluster))
        max_sev = max(cluster, key=lambda e: severity_rank.get(e.severity, 0)).severity
        result.append({
            "cluster_id": i,
            "start_time": cluster[0].timestamp,
            "end_time": cluster[-1].timestamp,
            "sources": sources,
            "max_severity": max_sev,
            "event_count": len(cluster),
            "events": [e.to_dict() if isinstance(e, Event) else e for e in cluster],
        })

    return result
