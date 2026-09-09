"""
connectors/log_parser.py
--------------------------
Parses user-uploaded files (plain text app logs, JSON exports, CSV alert
dumps) into normalized Event objects. This is what lets engineers drag in
raw log files from any tool, not just CloudWatch/Site24x7.
"""

import re
import csv
import json
import io
from datetime import datetime
from typing import List
from models.incident import Event

SEVERITY_KEYWORDS = {
    "critical": ["critical", "fatal", "panic", "down", "outage"],
    "error": ["error", "exception", "fail", "failed", "traceback"],
    "warning": ["warn", "warning", "degraded", "timeout", "retry"],
    "info": ["info", "notice", "started", "recovered", "ok"],
}

TIMESTAMP_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}",
    r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}",
]


def _guess_severity(line: str) -> str:
    lower = line.lower()
    for sev, keywords in SEVERITY_KEYWORDS.items():
        if any(k in lower for k in keywords):
            return sev
    return "info"


def _extract_timestamp(line: str, fallback: str) -> str:
    for pattern in TIMESTAMP_PATTERNS:
        m = re.search(pattern, line)
        if m:
            return m.group(0).replace(" ", "T") if "T" not in m.group(0) and "/" not in m.group(0) else m.group(0)
    return fallback


def parse_text_log(content: str, source_label: str = "AppLog") -> List[Event]:
    """Parse a plain-text log file, one event per non-empty line."""
    events = []
    now = datetime.utcnow().isoformat()
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        ts = _extract_timestamp(line, now)
        events.append(Event(
            timestamp=ts,
            source=source_label,
            severity=_guess_severity(line),
            message=line[:500],
            raw={"raw_line": line},
        ))
    return events


def parse_json_log(content: str, source_label: str = "JSONExport") -> List[Event]:
    """Parse a JSON array of alert/log objects. Tries common field names."""
    data = json.loads(content)
    if isinstance(data, dict):
        data = data.get("events") or data.get("data") or data.get("alerts") or [data]

    events = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ts = item.get("timestamp") or item.get("time") or item.get("alert_time") or datetime.utcnow().isoformat()
        msg = item.get("message") or item.get("description") or item.get("alert_desc") or json.dumps(item)[:300]
        sev = str(item.get("severity") or item.get("level") or _guess_severity(msg)).lower()
        events.append(Event(
            timestamp=str(ts),
            source=source_label,
            severity=sev,
            message=str(msg)[:500],
            resource=item.get("resource") or item.get("monitor_name") or item.get("instance_id"),
            raw=item,
        ))
    return events


def parse_csv_log(content: str, source_label: str = "CSVExport") -> List[Event]:
    events = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        ts = row.get("timestamp") or row.get("time") or datetime.utcnow().isoformat()
        msg = row.get("message") or row.get("description") or str(row)
        sev = (row.get("severity") or row.get("level") or _guess_severity(msg)).lower()
        events.append(Event(
            timestamp=str(ts),
            source=source_label,
            severity=sev,
            message=str(msg)[:500],
            resource=row.get("resource"),
            raw=row,
        ))
    return events


def parse_uploaded_file(filename: str, content: str) -> List[Event]:
    """Dispatch based on file extension."""
    lower = filename.lower()
    label = filename.rsplit(".", 1)[0][:40] or "Upload"
    try:
        if lower.endswith(".json"):
            return parse_json_log(content, source_label=label)
        elif lower.endswith(".csv"):
            return parse_csv_log(content, source_label=label)
        else:
            return parse_text_log(content, source_label=label)
    except Exception:
        # Fall back to plain-text parsing if structured parsing fails
        return parse_text_log(content, source_label=label)
