import time

import pytest

from services.ingestion.normalizers.binance_adapter import BinanceAdapter


@pytest.fixture
def sample_raw_trade_msg():
    now_ms = int(time.time() * 1000)
    return {"s": "BTCUSDT", "p": "65000.50", "q": "0.125", "t": 1001, "E": now_ms, "T": now_ms}


@pytest.fixture
def sample_canonical_trade(sample_raw_trade_msg):
    return BinanceAdapter().adapt(sample_raw_trade_msg)


@pytest.fixture
def override_ingestion_settings(monkeypatch):
    monkeypatch.setenv("INGESTION_CONSUMER_GROUP", "test-ingestion")
    monkeypatch.setenv("INGESTION_MAX_ALLOWED_STALENESS_SEC", "2.0")
