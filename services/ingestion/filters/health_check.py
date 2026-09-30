import time

from services.ingestion.filters.base import PipelineFilter


class HealthCheckFilter(PipelineFilter):
    """Live projection filter only; historical storage does not discard late trades."""

    def __init__(self, max_staleness_sec=5.0, max_future_skew_sec=2.0):
        self.max_staleness_sec = max_staleness_sec
        self.max_future_skew_sec = max_future_skew_sec

    async def filter(self, payload):
        value = payload.get("E", payload.get("T"))
        if type(value) is not int or value <= 0:
            return None
        age = time.time() - value / 1000
        if not -self.max_future_skew_sec <= age <= self.max_staleness_sec:
            return None
        return payload
