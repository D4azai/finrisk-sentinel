import time

import pytest

from services.ingestion.filters.health_check import HealthCheckFilter


@pytest.mark.asyncio
async def test_health_filter_passes_recent_payload():
    health_filter = HealthCheckFilter(max_staleness_sec=2.0)
    current_ms = int(time.time() * 1000)

    result = await health_filter.filter({"E": current_ms})
    assert result is not None


@pytest.mark.asyncio
async def test_health_filter_drops_stale_payload():
    health_filter = HealthCheckFilter(max_staleness_sec=2.0)
    stale_ms = int((time.time() - 10.0) * 1000)

    result = await health_filter.filter({"E": stale_ms})
    assert result is None
