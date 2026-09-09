"""
connectors/base_connector.py
-----------------------------
Every connector (CloudWatch, Site24x7, log files, ticketing systems, etc.)
implements this tiny interface. This is the plug-in point: to add a new
monitoring source, create a new file in this folder, subclass
BaseConnector, and implement fetch_events(). Nothing else in the app
needs to change.
"""

from abc import ABC, abstractmethod
from typing import List
from models.incident import Event


class BaseConnector(ABC):
    name = "base"

    @abstractmethod
    def fetch_events(self, start_time: str, end_time: str, **kwargs) -> List[Event]:
        """Return a list of normalized Event objects for the given window."""
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Whether real credentials are present. If False, connector should
        fall back to demo/mock data so the UI always has something to show."""
        return False
