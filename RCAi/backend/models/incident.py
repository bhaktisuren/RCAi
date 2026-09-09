"""
models/incident.py
-------------------
Defines the core data structures used across RCAi.

Every connector (CloudWatch, Site24x7, log files, manual notes) normalizes
its raw data into a list of `Event` objects. The correlation engine then
works only with this common shape, which is what makes it possible to mix
and match data sources.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime


@dataclass
class Event:
    """A single normalized event coming from any monitoring source."""
    timestamp: str            # ISO-8601 string
    source: str                # e.g. "CloudWatch", "Site24x7", "AppLog", "Manual"
    severity: str               # "info" | "warning" | "error" | "critical"
    message: str
    resource: Optional[str] = None   # e.g. instance id, service name, URL monitor
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    raw: Optional[dict] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Incident:
    """Represents one investigation session end to end."""
    incident_id: str
    title: str
    description: str
    reported_by: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    events: List[Event] = field(default_factory=list)
    anomalies: List[dict] = field(default_factory=list)
    correlation_clusters: List[dict] = field(default_factory=list)
    rca_report: Optional[dict] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self):
        d = asdict(self)
        d["events"] = [e.to_dict() if isinstance(e, Event) else e for e in self.events]
        return d
