from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from services.api.models import StrictBody
from services.common.decimal_types import Amount


class TransactionCreate(StrictBody):
    client_request_id: UUID
    market: str = Field(pattern=r"^[A-Z0-9]{4}$")
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    side: Literal["buy", "sell"]
    quantity: Amount = Field(gt=0)
    price: Amount = Field(gt=0)
    fees: Amount = Decimal("0")
    executed_at: AwareDatetime

    @field_validator("executed_at")
    @classmethod
    def completed_trade(cls, value):
        if value > datetime.now(UTC):
            raise ValueError("Completed trades cannot have a future execution time")
        return value.astimezone(UTC)


class TransactionView(BaseModel):
    id: UUID
    instrument_id: UUID | None = None
    is_demo: bool = False
    portfolio_id: UUID
    client_request_id: UUID
    market: str
    symbol: str
    currency: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    fees: Decimal
    executed_at: datetime
    created_at: datetime


class TransactionPage(BaseModel):
    items: list[TransactionView]
    next_cursor: UUID | None


class HoldingView(BaseModel):
    instrument: str
    instrument_id: UUID | None = None
    instrument_name: str | None = None
    isin: str | None = None
    is_demo: bool | None = None
    catalog_status: Literal["registered", "unregistered"]
    market: str
    symbol: str
    currency: str
    quantity: Decimal
    net_cash_flow: Decimal
    fees: Decimal
    last_executed_at: datetime


class HoldingsPage(BaseModel):
    items: list[HoldingView]
    next_cursor: str | None
