import time
import logging
from typing import Optional, Dict, Any
from services.ingestion.filters.base import PipelineFilter

logger = logging.getLogger("ingestion.filter.health")

class HealthCheckFilter(PipelineFilter):
    def __init__(self, max_staleness_sec: float = 5.0):
        self.max_staleness_sec = max_staleness_sec

    async def filter(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        event_time_ms = payload.get("E") or payload.get("T")
        if event_time_ms is None:
            return payload

        event_time_sec = event_time_ms / 1000.0
        now = time.time()
        latency = now - event_time_sec

        if latency > self.max_staleness_sec:
            logger.warning(f"Stale packet dropped. Latency: {latency:.2f}s exceeds threshold {self.max_staleness_sec}s")
            return None

        return payload