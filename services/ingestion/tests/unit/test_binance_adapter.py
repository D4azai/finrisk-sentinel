from datetime import datetime, timezone
from services.ingestion.normalizers.binance_adapter import BinanceAdapter


def test_binance_adapter_normalization():
    adapter = BinanceAdapter()
    raw_payload = {
        "s": "btcusdt",
        "p": "65000.50",
        "q": "1.25",
        "t": 987654,
        "T": 1700000000000
    }

    trade = adapter.adapt(raw_payload)

    assert trade.symbol == "BTCUSDT"
    assert trade.exchange == "binance"
    assert trade.price == 65000.50
    assert trade.volume == 1.25
    assert trade.sequence_id == 987654
    assert trade.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)