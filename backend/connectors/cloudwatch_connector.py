"""
connectors/cloudwatch_connector.py
------------------------------------
Pulls CloudWatch alarms / metrics / log events for an incident window.

If AWS credentials are set in .env, it will use boto3 to hit the real
CloudWatch API. If not, it returns realistic demo data so you can try
the full RCA pipeline without any AWS account.
"""

import os
import random
from datetime import datetime, timedelta
from typing import List
from models.incident import Event
from connectors.base_connector import BaseConnector


class CloudWatchConnector(BaseConnector):
    name = "CloudWatch"

    def __init__(self):
        self.access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
        self.secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        self.region = os.getenv("AWS_REGION", "ap-south-1")

    def is_configured(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def fetch_events(self, start_time: str, end_time: str, resource: str = "prod-app-server", **kwargs) -> List[Event]:
        if self.is_configured():
            return self._fetch_live(start_time, end_time, resource)
        return self._fetch_demo(start_time, end_time, resource)

    # ---------------- Live mode ----------------
    def _fetch_live(self, start_time, end_time, resource) -> List[Event]:
        import boto3  # imported lazily so boto3 is optional if unused
        client = boto3.client(
            "cloudwatch",
            region_name=self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )
        events = []
        alarms = client.describe_alarms_for_metric if False else None  # placeholder for future expansion
        resp = client.describe_alarms(StateValue="ALARM")
        for alarm in resp.get("MetricAlarms", []):
            events.append(Event(
                timestamp=str(alarm.get("StateUpdatedTimestamp", datetime.utcnow())),
                source="CloudWatch",
                severity="critical" if "critical" in alarm.get("AlarmName", "").lower() else "warning",
                message=alarm.get("AlarmDescription") or alarm.get("AlarmName"),
                resource=resource,
                metric_name=alarm.get("MetricName"),
                raw=alarm,
            ))
        return events

    # ---------------- Demo mode ----------------
    def _fetch_demo(self, start_time, end_time, resource) -> List[Event]:
        try:
            base = datetime.fromisoformat(start_time)
        except Exception:
            base = datetime.utcnow() - timedelta(hours=1)

        demo_events = [
            (0, "warning", "CPUUtilization crossed 75% threshold", "CPUUtilization", 76.2),
            (4, "warning", "CPUUtilization crossed 85% threshold", "CPUUtilization", 87.5),
            (9, "critical", "CPUUtilization sustained above 95% for 5 minutes", "CPUUtilization", 96.8),
            (10, "critical", "MemoryUtilization crossed 90% threshold", "MemoryUtilization", 92.1),
            (11, "error", "HealthCheckFailed for target group prod-tg-1 (2 consecutive failures)", "HealthyHostCount", 0),
            (12, "critical", "5xxErrorRate spiked to 42% of total requests", "HTTPCode_Target_5XX_Count", 42.0),
            (13, "critical", "Auto Scaling group prod-asg-1 failed to launch new instance: InsufficientInstanceCapacity", None, None),
            (15, "warning", "Database connections at 480/500 (96%) on RDS instance prod-db-1", "DatabaseConnections", 480),
        ]
        events = []
        for minute_offset, sev, msg, metric, val in demo_events:
            events.append(Event(
                timestamp=(base + timedelta(minutes=minute_offset)).isoformat(),
                source="CloudWatch",
                severity=sev,
                message=msg,
                resource=resource,
                metric_name=metric,
                metric_value=val,
                raw={"demo": True},
            ))
        return events
