"""
connectors/site24x7_connector.py
-----------------------------------
Pulls uptime / availability alerts from Site24x7 for the incident window.

If SITE24X7_API_KEY is set in .env, it calls the real Site24x7 REST API.
Otherwise it returns realistic demo data.
"""

import os
from datetime import datetime, timedelta
from typing import List
import urllib.request
import json
from models.incident import Event
from connectors.base_connector import BaseConnector


class Site24x7Connector(BaseConnector):
    name = "Site24x7"
    API_BASE = "https://www.site24x7.com/api"

    def __init__(self):
        self.api_key = os.getenv("SITE24X7_API_KEY", "")
        self.account_id = os.getenv("SITE24X7_ACCOUNT_ID", "")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.account_id)

    def fetch_events(self, start_time: str, end_time: str, monitor_name: str = "prod-web-app", **kwargs) -> List[Event]:
        if self.is_configured():
            return self._fetch_live(start_time, end_time, monitor_name)
        return self._fetch_demo(start_time, end_time, monitor_name)

    # ---------------- Live mode ----------------
    def _fetch_live(self, start_time, end_time, monitor_name) -> List[Event]:
        req = urllib.request.Request(
            f"{self.API_BASE}/alerts",
            headers={
                "Authorization": f"Zoho-oauthtoken {self.api_key}",
                "Accept": "application/json; version=2.1",
            },
        )
        events = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                for alert in data.get("data", []):
                    events.append(Event(
                        timestamp=alert.get("alert_time", datetime.utcnow().isoformat()),
                        source="Site24x7",
                        severity=alert.get("severity", "warning").lower(),
                        message=alert.get("alert_desc", "Site24x7 alert"),
                        resource=alert.get("monitor_name", monitor_name),
                        raw=alert,
                    ))
        except Exception as e:
            events.append(Event(
                timestamp=datetime.utcnow().isoformat(),
                source="Site24x7",
                severity="warning",
                message=f"Could not reach Site24x7 API ({e}); showing no live data.",
                resource=monitor_name,
            ))
        return events

    # ---------------- Demo mode ----------------
    def _fetch_demo(self, start_time, end_time, monitor_name) -> List[Event]:
        try:
            base = datetime.fromisoformat(start_time)
        except Exception:
            base = datetime.utcnow() - timedelta(hours=1)

        demo_events = [
            (8, "warning", "Response time degraded: 3200ms (baseline 400ms)"),
            (10, "critical", "DOWN alert: prod-web-app is not responding (HTTP timeout)"),
            (10, "critical", "DOWN alert: /api/checkout endpoint returning HTTP 503"),
            (16, "info", "UP alert: prod-web-app recovered after 6 minutes downtime"),
            (16, "info", "Root cause tag suggested by Site24x7 AI Ops: 'Upstream server error'"),
        ]
        events = []
        for minute_offset, sev, msg in demo_events:
            events.append(Event(
                timestamp=(base + timedelta(minutes=minute_offset)).isoformat(),
                source="Site24x7",
                severity=sev,
                message=msg,
                resource=monitor_name,
                raw={"demo": True},
            ))
        return events
