import pytest

from services.market_data.connectors.binance_ws import BinanceWSConnector
from services.market_data.connectors.factory import ConnectorFactory


def test_connector_factory_creates_binance_connector():
    connector = ConnectorFactory.create("binance", ["btcusdt"])
    assert isinstance(connector, BinanceWSConnector)
    assert connector.symbols == ["btcusdt"]


def test_connector_factory_raises_invalid_exchange():
    with pytest.raises(ValueError, match="Unsupported exchange connector"):
        ConnectorFactory.create("unsupported_exchange", ["btcusdt"])
