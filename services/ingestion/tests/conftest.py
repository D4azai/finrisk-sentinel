import pytest
import time
from datetime import datetime, timezone
from services.ingestion.normalizers.base import CanonicalTrade

@pytest.fixture
def sample_raw_trade_msg() -> dict:
    """Provides a mock raw frame received from the Market Data ZeroMQ stream."""
    now_ms = int(time.time() * 1000)
    return {
        "s": "BTCUSDT",
        "p": "65000.50",
        "q": "0.125",
        "t": 1001,
        "E": now_ms,
        "T": now_ms
    }

@pytest.fixture
def sample_canonical_trade() -> CanonicalTrade:
    """Provides an expected CanonicalTrade domain model instance."""
    return CanonicalTrade(
        symbol="BTCUSDT",
        exchange="binance",
        price=65000.50,
        volume=0.125,
        sequence_id=1001,
        timestamp=datetime.now(timezone.utc)
    )

@pytest.fixture
def override_ingestion_settings(monkeypatch):
    """Overrides environment settings for isolated test execution."""
    monkeypatch.setenv("INGESTION_ZMQ_SUB_ENDPOINT", "inproc://test_market_pub")
    monkeypatch.setenv("INGESTION_ZMQ_CLEAN_PUB_ENDPOINT", "inproc://test_clean_pub")
    monkeypatch.setenv("INGESTION_MAX_ALLOWED_STALENESS_SEC", "2.0")