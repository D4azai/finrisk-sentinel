import pytest

from services.market_data.engine.connection_manager import ResilientConnectionManager


@pytest.mark.asyncio
async def test_stream_with_retry_yields_data():
    async def mock_stream():
        yield {"s": "BTCUSDT", "p": "50000"}
        yield {"s": "BTCUSDT", "p": "50001"}

    manager = ResilientConnectionManager(base_delay=0.01, max_delay=0.1)
    received = []

    async for frame in manager.stream_with_retry(mock_stream):
        received.append(frame)
        if len(received) == 2:
            break

    assert len(received) == 2
    assert received[0]["p"] == "50000"
