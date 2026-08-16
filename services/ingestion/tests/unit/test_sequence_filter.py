import pytest
from services.ingestion.filters.sequence_check import SequenceValidationFilter


@pytest.mark.asyncio
async def test_sequence_filter_accepts_initial_and_consecutive_ids():
    seq_filter = SequenceValidationFilter()

    first = await seq_filter.filter({"s": "BTCUSDT", "t": 100})
    second = await seq_filter.filter({"s": "BTCUSDT", "t": 101})

    assert first is not None
    assert second is not None


@pytest.mark.asyncio
async def test_sequence_filter_drops_out_of_order_duplicate():
    seq_filter = SequenceValidationFilter()

    await seq_filter.filter({"s": "BTCUSDT", "t": 100})
    duplicate = await seq_filter.filter({"s": "BTCUSDT", "t": 100})
    out_of_order = await seq_filter.filter({"s": "BTCUSDT", "t": 99})

    assert duplicate is None
    assert out_of_order is None