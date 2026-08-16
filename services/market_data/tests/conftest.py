import pytest
import time

@pytest.fixture
def sample_raw_binance_payload() -> dict:
    """Provides a standard mock Binance trade WebSocket payload."""
    now_ms = int(time.time() * 1000)
    return {
        "e": "trade",
        "E": now_ms,
        "s": "BTCUSDT",
        "t": 1234567,
        "p": "65000.50",
        "q": "0.500",
        "b": 88888,
        "a": 88889,
        "T": now_ms,
        "m": True,
        "M": True
    }

@pytest.fixture
def override_market_data_settings(monkeypatch):
    """Overrides environment settings for isolated test execution."""
    monkeypatch.setenv("MARKET_DATA_EXCHANGE_NAME", "binance")
    monkeypatch.setenv("MARKET_DATA_SYMBOLS", '["btcusdt"]')
    monkeypatch.setenv("MARKET_DATA_ZMQ_PUB_ENDPOINT", "inproc://test_market_pub")