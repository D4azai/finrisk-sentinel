from typing import Type

from services.market_data.connectors.base import BaseExchangeConnector
from services.market_data.connectors.binance_ws import BinanceWSConnector


class ConnectorFactory:
    _registry: dict[str, Type[BaseExchangeConnector]] = {
        "binance": BinanceWSConnector,
    }

    @classmethod
    def create(cls, exchange_name: str, symbols: list[str]) -> BaseExchangeConnector:
        connector_cls = cls._registry.get(exchange_name.lower())
        if not connector_cls:
            raise ValueError(f"Unsupported exchange connector: '{exchange_name}'")
        return connector_cls(symbols=symbols)
