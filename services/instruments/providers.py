"""Bounded provider boundary. Fresh price availability is not a trading-risk signal."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from services.common.decimal_types import Amount
from services.instruments.models import InstrumentView


class ProviderInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    markets: tuple[str, ...]
    mode: Literal["demo", "realtime", "delayed", "end_of_day"]
    supports_history: bool = False


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: UUID
    provider: str = Field(min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price: Amount = Field(gt=0)
    as_of: AwareDatetime
    received_at: AwareDatetime
    mode: Literal["demo", "realtime", "delayed", "end_of_day"]
    session: Literal["open", "closed", "unknown"] = "unknown"

    @model_validator(mode="after")
    def ordered_timestamps(self):
        if self.as_of > self.received_at + timedelta(seconds=5):
            raise ValueError("Quote time is later than receipt time")
        return self


class QuoteResult(BaseModel):
    status: Literal[
        "available",
        "stale",
        "demo",
        "delayed",
        "end_of_day",
        "session_unknown",
        "market_closed",
        "missing",
        "not_configured",
        "unavailable",
        "invalid",
    ]
    quote: Quote | None = None
    age_seconds: int | None = None
    reason: str


class QuoteProvider(Protocol):
    info: ProviderInfo

    async def get_quote(self, instrument: InstrumentView) -> Quote | None: ...


class ProviderUnavailable(Exception):
    """Adapters translate transport/authentication failures without exposing credentials."""


class DemoQuoteProvider:
    info = ProviderInfo(name="demo-fixture", markets=("XCAS", "XNYS", "XNAS"), mode="demo")

    def __init__(self, *, environment: str, enabled: bool):
        if environment not in {"development", "test"} or not enabled:
            raise ValueError("Demo provider requires explicit non-production enablement")

    async def get_quote(self, instrument: InstrumentView) -> Quote | None:
        if not instrument.is_demo or instrument.market not in self.info.markets:
            return None
        return Quote(
            instrument_id=instrument.id,
            provider=self.info.name,
            currency=instrument.currency,
            price="100.00",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            received_at=datetime.now(UTC),
            mode="demo",
            session="unknown",
        )


async def fetch_quote(
    provider: QuoteProvider | None,
    instrument: InstrumentView,
    *,
    now: datetime,
    max_age_seconds: int = 300,
    timeout_seconds: float = 5,
    allow_demo: bool = False,
) -> QuoteResult:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("An aware evaluation time is required")
    if max_age_seconds < 1 or not 0 < timeout_seconds <= 30:
        raise ValueError("Invalid freshness or timeout budget")
    if provider is None or instrument.market not in provider.info.markets:
        return QuoteResult(
            status="not_configured", reason="No provider configured for this listing"
        )
    if (instrument.is_demo or provider.info.mode == "demo") and not allow_demo:
        return QuoteResult(status="not_configured", reason="Demo data is disabled")
    try:
        async with asyncio.timeout(timeout_seconds):
            quote = await provider.get_quote(instrument)
    except (ProviderUnavailable, TimeoutError):
        return QuoteResult(status="unavailable", reason="Provider temporarily unavailable")
    except ValidationError:
        return QuoteResult(status="invalid", reason="Provider returned a malformed quote")
    if quote is None:
        return QuoteResult(status="missing", reason="Provider has no quote for this listing")
    if (
        quote.instrument_id != instrument.id
        or quote.currency != instrument.currency
        or quote.provider != provider.info.name
        or quote.mode != provider.info.mode
        or (quote.mode == "demo") != instrument.is_demo
        or quote.received_at > now + timedelta(seconds=5)
        or quote.as_of > now + timedelta(seconds=5)
    ):
        return QuoteResult(
            status="invalid", reason="Provider quote failed identity or time validation"
        )
    age = max(0, int((now - quote.as_of).total_seconds()))
    if quote.mode == "demo":
        status, reason = "demo", "Synthetic fixed-price fixture; not market data"
    elif age > max_age_seconds:
        status, reason = "stale", "Quote exceeds the freshness budget"
    elif quote.mode in {"delayed", "end_of_day"}:
        status, reason = quote.mode, "Provider does not supply a real-time quote"
    elif quote.session == "unknown":
        status, reason = "session_unknown", "Trading session has not been established"
    elif quote.session == "closed":
        status, reason = "market_closed", "Provider reports that the trading session is closed"
    else:
        status, reason = (
            "available",
            "Recent quote in an open session; not a trading-risk assessment",
        )
    return QuoteResult(status=status, quote=quote, age_seconds=age, reason=reason)
