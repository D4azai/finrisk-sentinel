from abc import ABC, abstractmethod
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CanonicalTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    price: float
    volume: float
    sequence_id: int
    timestamp: datetime


class BaseAdapter(ABC):
    @abstractmethod
    def adapt(self, raw_payload: dict) -> CanonicalTrade:
        """Adapts exchange-specific raw data into standard CanonicalTrade model."""
        pass