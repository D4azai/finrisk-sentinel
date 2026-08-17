from typing import Type
from services.market_data.connectors.base import BaseExchangeConnector

class ConnectorFactory:
    _registry: dict[str, Type[BaseExchangeConnector]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to dynamically register connector implementations."""
        def decorator(connector_cls: Type[BaseExchangeConnector]):
            cls._registry[name.lower()] = connector_cls
            return connector_cls
        return decorator

    @classmethod
    def create(cls, exchange_name: str, symbols: list[str]) -> BaseExchangeConnector:
        connector_cls = cls._registry.get(exchange_name.lower())
        if not connector_cls:
            raise ValueError(
                f"Unsupported exchange connector: '{exchange_name}'. "
                f"Available connectors: {list(cls._registry.keys())}"
            )
        return connector_cls(symbols=symbols)