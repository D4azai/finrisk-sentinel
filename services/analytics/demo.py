"""Repeatable, fictional market fixtures. These are not exchange calendars or prices."""

import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from services.analytics.market import import_market
from services.instruments.catalog import import_catalog


async def seed_demo(connection, *, environment, now=None):
    if environment not in {"development", "test"}:
        raise ValueError("Synthetic market fixtures are forbidden in production")
    now = now or datetime.now(UTC)
    listings = [
        ("XCAS", "DEMO-MA", "MAD", "Morocco demo equity (fictional)"),
        ("XNYS", "DEMO-US", "USD", "International demo equity (fictional)"),
        ("XCAS", "DEMO-SPIKE", "MAD", "Anomaly example (fictional)"),
    ]
    catalog = {
        "schema_version": 1,
        "instruments": [
            dict(
                market=m,
                symbol=s,
                currency=c,
                name=n,
                is_demo=True,
                source="FinRisk synthetic development fixture; not an exchange listing",
                verified_at=now.isoformat(),
            )
            for m, s, c, n in listings
        ],
    }
    sessions = []
    for offset in range(-120, 46):
        day = now.date() + timedelta(days=offset)
        if day.weekday() < 5:
            for market in ("XCAS", "XNYS"):
                sessions.append(
                    dict(
                        market=market,
                        session_date=day.isoformat(),
                        opens_at=datetime.combine(day, time(9), UTC).isoformat(),
                        closes_at=datetime.combine(day, time(16), UTC).isoformat(),
                    )
                )
    bars = []
    for s in sessions:
        as_of = datetime.fromisoformat(s["closes_at"])
        if as_of > now:
            continue
        for market, symbol, currency, _ in listings:
            if market != s["market"]:
                continue
            ordinal = as_of.date().toordinal()
            if symbol == "DEMO-SPIKE":
                price = Decimal("100") if ordinal % 2 else Decimal("125")
            else:
                price = Decimal("100" if currency == "MAD" else "180") + Decimal(
                    ordinal % 20
                ) * Decimal("0.02")
            bars.append(
                dict(
                    market=market,
                    symbol=symbol,
                    currency=currency,
                    session_date=s["session_date"],
                    as_of=s["closes_at"],
                    open=str(price),
                    high=str(price + 1),
                    low=str(price - 1),
                    close=str(price),
                    volume=str(1000 + ordinal % 9 * 20),
                    adjusted=True,
                )
            )
    as_of = max(b["as_of"] for b in bars)
    batch = dict(
        source="finrisk-demo-v1",
        is_demo=True,
        sessions=sessions,
        bars=bars,
        fx=[
            dict(base_currency="USD", quote_currency="MAD", rate="10", as_of=as_of),
            dict(base_currency="MAD", quote_currency="USD", rate="0.1", as_of=as_of),
        ],
    )
    async with connection.transaction():
        await import_catalog(
            connection, json.dumps(catalog).encode(), environment=environment, allow_demo=True
        )
        result = await import_market(
            connection, json.dumps(batch).encode(), environment=environment, allow_demo=True
        )
    return result
