from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request

from services.analytics.engine import load_history
from services.api.database import transaction
from services.instruments.models import InstrumentPage, InstrumentView
from services.instruments.providers import Quote, QuoteResult, fetch_quote


def register_instruments(app, authenticated):
    @app.get("/v1/market-data/providers")
    async def providers(request: Request, identity=Depends(authenticated)):
        async with transaction(
            request.app.state.pool,
            identity,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (conn, _, _role):
            provider = request.app.state.quote_provider
            sources = await conn.fetch("""SELECT f.source,i.is_demo,count(*) AS instruments
                FROM saas.instrument_feeds f JOIN saas.instruments i ON i.id=f.instrument_id
                GROUP BY f.source,i.is_demo ORDER BY f.source""")
            return {
                "configured": [provider.info.model_dump(mode="json")] if provider else [],
                "stored_daily_sources": [dict(r) for r in sources],
                "historical_import": True,
                "live_provider_configured": False,
            }

    @app.get("/v1/instruments", response_model=InstrumentPage)
    async def list_instruments(
        request: Request,
        q: str | None = Query(None, min_length=1, max_length=80),
        market: str | None = Query(None, pattern=r"^[A-Z0-9]{4}$"),
        currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"),
        active: bool | None = None,
        cursor: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (conn, _, _role):
            rows = await conn.fetch(
                """SELECT * FROM saas.instruments
                   WHERE ($1::text IS NULL OR strpos(lower(name),lower($1))>0
                       OR strpos(lower(symbol),lower($1))>0 OR isin=$1)
                   AND ($2::text IS NULL OR market=$2)
                   AND ($3::text IS NULL OR currency=$3)
                   AND ($4::boolean IS NULL OR active=$4)
                   AND ($5::uuid IS NULL OR id>$5) ORDER BY id LIMIT $6""",
                q,
                market,
                currency,
                active,
                cursor,
                limit + 1,
            )
            return {
                "items": [dict(r) for r in rows[:limit]],
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
            }

    @app.get("/v1/instruments/{instrument_id}", response_model=InstrumentView)
    async def instrument(
        instrument_id: UUID,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (conn, _, _role):
            row = await conn.fetchrow("SELECT * FROM saas.instruments WHERE id=$1", instrument_id)
            if row is None:
                raise HTTPException(404, "Instrument not found")
            return dict(row)

    @app.get("/v1/instruments/{instrument_id}/quote", response_model=QuoteResult)
    async def quote(
        instrument_id: UUID,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (conn, _, _role):
            row = await conn.fetchrow("SELECT * FROM saas.instruments WHERE id=$1", instrument_id)
            if row is None:
                raise HTTPException(404, "Instrument not found")
            listing = InstrumentView.model_validate(dict(row))
            history = await load_history(conn, row, datetime.now(UTC), limit=1)
            if history["bars"]:
                bar = history["bars"][-1]
                status = history["quality"]
                return QuoteResult(
                    status=status if status in {"demo", "end_of_day", "stale"} else "invalid",
                    reason=history["reason"],
                    age_seconds=max(0, int((datetime.now(UTC) - bar["as_of"]).total_seconds())),
                    quote=Quote(
                        instrument_id=instrument_id,
                        provider=bar["source"],
                        currency=listing.currency,
                        price=format(bar["close"], "f"),
                        as_of=bar["as_of"],
                        received_at=bar["received_at"],
                        mode="demo" if listing.is_demo else "end_of_day",
                        session="closed",
                    ),
                )
        return await fetch_quote(
            request.app.state.quote_provider,
            listing,
            now=datetime.now(UTC),
            allow_demo=request.app.state.settings.allow_demo_market_data,
        )
