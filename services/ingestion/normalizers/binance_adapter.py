from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from services.common.contracts import utcnow
from services.ingestion.normalizers.base import BaseAdapter, CanonicalTrade


class BinanceTrade(BaseModel):
    e: Literal["trade"] = "trade"
    s: str = Field(pattern=r"^[a-zA-Z0-9]{1,30}$")
    p: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)
    q: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)
    t: int = Field(ge=0, le=9223372036854775807, strict=True)
    T: int = Field(gt=0, le=253402300799000, strict=True)
    E: int | None = Field(default=None, gt=0, le=253402300799000, strict=True)

    @field_validator("p", "q", mode="before")
    @classmethod
    def exact_wire_value(cls, value):
        if not isinstance(value, str):
            raise ValueError("Exchange quantities must be decimal strings")
        return value


class BinanceAdapter(BaseAdapter):
    def adapt(self, raw_payload: dict, *, received_at=None, now=None) -> CanonicalTrade:
        raw = BinanceTrade.model_validate(raw_payload)
        symbol = raw.s.upper()
        instrument = f"binance:spot:{symbol}"
        now = now or utcnow()
        return CanonicalTrade(
            event_id=f"{instrument}:{raw.t}",
            symbol=symbol,
            instrument_id=instrument,
            price=raw.p,
            volume=raw.q,
            sequence_id=raw.t,
            timestamp=datetime.fromtimestamp(raw.T / 1000, tz=timezone.utc),
            source_event_at=datetime.fromtimestamp((raw.E or raw.T) / 1000, tz=timezone.utc),
            received_at=received_at or now,
            normalized_at=now,
        )
