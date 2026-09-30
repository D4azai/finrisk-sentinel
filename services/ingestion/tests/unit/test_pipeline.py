import time

import pytest

from services.ingestion.filters.health_check import HealthCheckFilter
from services.ingestion.filters.sequence_check import SequenceValidationFilter
from services.ingestion.pipeline.processing_chain import IngestionPipeline


@pytest.mark.asyncio
async def test_pipeline_execution_success():
    pipeline = IngestionPipeline(
        [SequenceValidationFilter(), HealthCheckFilter(max_staleness_sec=5.0)]
    )

    valid_payload = {"s": "BTCUSDT", "t": 1, "E": int(time.time() * 1000)}
    result = await pipeline.execute(valid_payload)

    assert result == valid_payload


@pytest.mark.asyncio
async def test_pipeline_execution_rejected_by_filter():
    pipeline = IngestionPipeline(
        [SequenceValidationFilter(), HealthCheckFilter(max_staleness_sec=1.0)]
    )

    stale_payload = {"s": "BTCUSDT", "t": 1, "E": int((time.time() - 5.0) * 1000)}
    result = await pipeline.execute(stale_payload)

    assert result is None
