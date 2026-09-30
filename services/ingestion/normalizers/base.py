from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer, field_validator


class CanonicalTrade(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    event_id: str
    symbol: str = Field(pattern=r"^[A-Z0-9]{1,30}$")
    exchange: Literal["binance"] = "binance"
    market_type: Literal["spot"] = "spot"
    instrument_id: str
    price: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)
    volume: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)
    sequence_id: int = Field(ge=0, le=9223372036854775807, strict=True)
    timestamp: AwareDatetime
    source_event_at: AwareDatetime
    received_at: AwareDatetime
    normalized_at: AwareDatetime
    quality_flags: tuple[str, ...] = ()

    @field_serializer("sequence_id", when_used="json")
    def serialize_sequence(self, value: int) -> str:
        # Preserve 64-bit identifiers for JavaScript and other JSON consumers.
        return str(value)

    @field_validator("sequence_id", mode="before")
    @classmethod
    def parse_sequence(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        return value


class BaseAdapter(ABC):
    @abstractmethod
    def adapt(self, raw_payload: dict, **kwargs) -> CanonicalTrade:
        pass
