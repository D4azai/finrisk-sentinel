import pytest

from services.ingestion.filters.sequence_check import SequenceValidationFilter


async def test_filter_has_no_state_before_durable_commit():
    sequence = SequenceValidationFilter()
    await sequence.filter({"s": "BTCUSDT", "t": 999999})
    assert await sequence.filter({"s": "BTCUSDT", "t": 1}) is not None
    assert await sequence.filter({"s": "BTCUSDT", "t": 1}) is not None


@pytest.mark.parametrize(
    "payload",
    [{}, {"s": "BTCUSDT", "t": True}, {"s": "BTCUSDT", "t": -1}, {"s": "BTCUSDT", "t": "1"}],
)
async def test_bad_sequence_shape(payload):
    assert await SequenceValidationFilter().filter(payload) is None
