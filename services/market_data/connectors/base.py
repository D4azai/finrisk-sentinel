from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any

class BaseExchangeConnector(ABC):
    @abstractmethod
    async def connect_and_stream(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Establishes WebSocket stream and yields raw JSON payloads."""
        yield {}