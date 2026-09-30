import time

import pytest


@pytest.fixture
def sample_raw_binance_payload():
    now_ms = int(time.time() * 1000)
    return {
        "e": "trade",
        "E": now_ms,
        "s": "BTCUSDT",
        "t": 1234567,
        "p": "65000.50",
        "q": "0.500",
        "T": now_ms,
        "m": True,
    }


@pytest.fixture
def override_market_data_settings(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_EXCHANGE_NAME", "binance")
    monkeypatch.setenv("MARKET_DATA_SYMBOLS", '["btcusdt"]')
