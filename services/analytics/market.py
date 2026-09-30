import hashlib
from datetime import UTC, date, datetime
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from services.common.decimal_types import Amount


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Session(Strict):
    market: str = Field(pattern=r"^[A-Z0-9]{4}$")
    session_date: date
    opens_at: AwareDatetime
    closes_at: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.closes_at <= self.opens_at:
            raise ValueError("Session close must follow open")
        if (self.closes_at - self.opens_at).total_seconds() > 86400:
            raise ValueError("Session cannot exceed 24 hours")
        return self


class Bar(Strict):
    market: str = Field(pattern=r"^[A-Z0-9]{4}$")
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    session_date: date
    as_of: AwareDatetime
    open: Amount = Field(gt=0)
    high: Amount = Field(gt=0)
    low: Amount = Field(gt=0)
    close: Amount = Field(gt=0)
    volume: Amount
    adjusted: bool = Field(strict=True)

    @model_validator(mode="after")
    def ohlc(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Inconsistent OHLC bounds")
        if self.as_of > datetime.now(UTC):
            raise ValueError("Only completed bars may be imported")
        return self


class FX(Strict):
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate: Amount = Field(gt=0)
    as_of: AwareDatetime

    @model_validator(mode="after")
    def valid_pair(self):
        if self.base_currency == self.quote_currency or self.as_of > datetime.now(UTC):
            raise ValueError("Invalid FX pair or future timestamp")
        return self


class MarketImport(Strict):
    source: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    is_demo: bool = Field(strict=True)
    max_age_seconds: int = Field(default=345600, ge=60, le=604800)
    sessions: list[Session] = Field(default_factory=list, max_length=10000)
    bars: list[Bar] = Field(default_factory=list, max_length=10000)
    fx: list[FX] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def unique(self):
        groups = [
            ([(s.market, s.session_date) for s in self.sessions]),
            [(b.market, b.symbol, b.currency, b.session_date) for b in self.bars],
            [(f.base_currency, f.quote_currency, f.as_of) for f in self.fx],
        ]
        if any(len(g) != len(set(g)) for g in groups):
            raise ValueError("Duplicate record in import")
        if not (self.bars or self.sessions or self.fx):
            raise ValueError("Empty market import")
        return self


async def import_market(connection, raw: bytes, *, environment: str, allow_demo=False):
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Market import exceeds 8 MiB")
    batch = MarketImport.model_validate_json(raw)
    if environment not in {"development", "test", "production"}:
        raise ValueError("Invalid environment")
    if batch.is_demo and (environment == "production" or not allow_demo):
        raise ValueError("Demo imports require explicit non-production enablement")
    digest = hashlib.sha256(raw).hexdigest()
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(7183454)")
        if await connection.fetchval(
            "SELECT 1 FROM saas.market_imports WHERE content_sha256=$1", digest
        ):
            return {"status": "duplicate", "bars": 0}
        for s in batch.sessions:
            values = (
                s.market,
                s.session_date,
                batch.is_demo,
                s.opens_at,
                s.closes_at,
                batch.source,
            )
            old = await connection.fetchrow(
                "SELECT * FROM saas.market_sessions WHERE market=$1 AND session_date=$2 AND is_demo=$3",
                *values[:3],
            )
            if old and any(
                old[k] != v for k, v in zip(("opens_at", "closes_at", "source"), values[3:])
            ):
                raise ValueError("Conflicting session; calendar corrections require review")
            await connection.execute(
                "INSERT INTO saas.market_sessions VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING",
                *values,
            )
        for b in batch.bars:
            instrument = await connection.fetchrow(
                "SELECT id,is_demo FROM saas.instruments WHERE market=$1 AND symbol=$2 AND currency=$3",
                b.market,
                b.symbol,
                b.currency,
            )
            if instrument is None or instrument["is_demo"] != batch.is_demo:
                raise ValueError("Unregistered listing or mismatched demo provenance")
            close = await connection.fetchval(
                "SELECT closes_at FROM saas.market_sessions WHERE market=$1 AND session_date=$2 AND is_demo=$3",
                b.market,
                b.session_date,
                batch.is_demo,
            )
            if close != b.as_of:
                raise ValueError("Bar must match a known session close")
            feed = await connection.fetchrow(
                "SELECT * FROM saas.instrument_feeds WHERE instrument_id=$1", instrument["id"]
            )
            if feed and (
                feed["source"] != batch.source or feed["max_age_seconds"] != batch.max_age_seconds
            ):
                raise ValueError("Changing the selected feed requires operator review")
            await connection.execute(
                "INSERT INTO saas.instrument_feeds VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                instrument["id"],
                batch.source,
                batch.max_age_seconds,
            )
            old = await connection.fetchrow(
                "SELECT * FROM saas.price_bars WHERE instrument_id=$1 AND source=$2 AND session_date=$3",
                instrument["id"],
                batch.source,
                b.session_date,
            )
            if old and any(
                old[k] != getattr(b, k)
                for k in ("as_of", "open", "high", "low", "close", "volume", "adjusted")
            ):
                raise ValueError(
                    "Conflicting historical bar; immutable records cannot be overwritten"
                )
            await connection.execute(
                """INSERT INTO saas.price_bars
                (id,instrument_id,source,session_date,as_of,open,high,low,close,volume,adjusted,is_demo)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT DO NOTHING""",
                uuid4(),
                instrument["id"],
                batch.source,
                b.session_date,
                b.as_of,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.adjusted,
                batch.is_demo,
            )
        for f in batch.fx:
            old = await connection.fetchval(
                "SELECT rate FROM saas.fx_rates WHERE base_currency=$1 AND quote_currency=$2 AND source=$3 AND as_of=$4 AND is_demo=$5",
                f.base_currency,
                f.quote_currency,
                batch.source,
                f.as_of,
                batch.is_demo,
            )
            if old is not None and old != f.rate:
                raise ValueError("Conflicting FX observation")
            await connection.execute(
                """INSERT INTO saas.fx_rates
                (id,base_currency,quote_currency,rate,as_of,source,is_demo)
                VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING""",
                uuid4(),
                f.base_currency,
                f.quote_currency,
                f.rate,
                f.as_of,
                batch.source,
                batch.is_demo,
            )
        await connection.execute(
            "INSERT INTO saas.market_imports(content_sha256,source,bar_count) VALUES($1,$2,$3)",
            digest,
            batch.source,
            len(batch.bars),
        )
    return {"status": "imported", "bars": len(batch.bars)}
