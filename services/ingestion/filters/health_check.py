import time
import logging
from typing import Optional, Dict, Any
from services.ingestion.filters.base import PipelineFilter
from services.logging_helpers import redact_symbol

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
            symbol = payload.get("s") or payload.get("symbol")
            logger.warning("Stale packet dropped for %s. Latency: %.2fs exceeds threshold %s", redact_symbol(symbol), latency, self.max_staleness_sec)
            return None

        return payload