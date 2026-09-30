from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict


class BaseExchangeConnector(ABC):
    @abstractmethod
    async def connect_and_stream(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Establishes WebSocket stream and yields raw JSON payloads."""
        yield {}
