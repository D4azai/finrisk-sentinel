from datetime import date, datetime
from decimal import Decimal, localcontext
from statistics import median
from uuid import UUID


def wire(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    return value


async def load_history(conn, instrument, now, limit=61):
    feed = await conn.fetchrow(
        "SELECT * FROM saas.instrument_feeds WHERE instrument_id=$1", instrument["id"]
    )
    result = {
        "instrument_id": instrument["id"],
        "source": None,
        "quality": "missing",
        "bars": [],
        "reason": "No stored provider history",
    }
    if not feed:
        return result
    result["source"] = feed["source"]
    rows = await conn.fetch(
        """SELECT * FROM saas.price_bars WHERE instrument_id=$1 AND source=$2
        AND as_of<=$3 ORDER BY as_of DESC LIMIT $4""",
        instrument["id"],
        feed["source"],
        now,
        limit,
    )
    bars = list(reversed([dict(r) for r in rows]))
    result["bars"] = bars
    if not bars:
        return result
    calendar = await conn.fetchrow(
        """SELECT max(closes_at) FILTER(WHERE closes_at<=$3) AS expected,
        max(closes_at) AS coverage,
        count(*) FILTER(WHERE closes_at BETWEEN $4 AND $5) AS expected_count
        FROM saas.market_sessions WHERE market=$1 AND is_demo=$2""",
        instrument["market"],
        instrument["is_demo"],
        now,
        bars[0]["as_of"],
        bars[-1]["as_of"],
    )
    if (now - bars[-1]["as_of"]).total_seconds() > feed["max_age_seconds"]:
        quality, reason = "stale", "Latest completed bar exceeds the feed freshness budget"
    elif calendar["expected"] != bars[-1]["as_of"] or calendar["expected_count"] != len(bars):
        quality, reason = "gap", "Missing completed sessions in the selected history window"
    elif calendar["coverage"] is None or calendar["coverage"] < now:
        quality, reason = "calendar_unknown", "Session calendar does not cover the evaluation time"
    else:
        quality = "demo" if instrument["is_demo"] else "end_of_day"
        reason = (
            "Synthetic daily bars"
            if instrument["is_demo"]
            else "Completed daily bars; not a live quote"
        )
    result.update(quality=quality, reason=reason)
    return result


def detect_anomalies(history):
    bars = history["bars"][-31:]
    result = {
        "model_version": "daily-robust-v1",
        "status": "insufficient_data",
        "is_demo": any(b["is_demo"] for b in bars),
        "quality": history["quality"],
        "reasons": [],
        "evidence": {},
        "bar_ids": [b["id"] for b in bars],
        "parameters": {
            "minimum_bars": 31,
            "price_move_pct": "5",
            "modified_z": "3.5",
            "volume_multiple": "3",
            "mad_floor": "0.001",
            "low_volume_ratio": "0.2",
        },
    }
    if history["quality"] not in {"demo", "end_of_day"}:
        result["reasons"] = [history["reason"]]
        return wire(result)
    if len(bars) < 31 or not all(b["adjusted"] for b in bars):
        result["reasons"] = ["Need 31 complete, consistently adjusted daily bars"]
        return wire(result)
    with localcontext() as ctx:
        ctx.prec = 128
        returns = [b["close"] / a["close"] - 1 for a, b in zip(bars, bars[1:])]
        baseline = returns[:-1]
        center = median(baseline)
        mad = median([abs(r - center) for r in baseline])
        latest = returns[-1]
        score = Decimal("0.6745") * (latest - center) / max(mad, Decimal("0.001"))
        volume_baseline = median([b["volume"] for b in bars[:-1]])
        ratio = bars[-1]["volume"] / volume_baseline if volume_baseline else None
        if abs(latest) >= Decimal("0.05") or abs(score) > Decimal("3.5"):
            result["reasons"].append("Unusual daily price move")
        if (ratio is not None and ratio >= 3) or (not volume_baseline and bars[-1]["volume"] > 0):
            result["reasons"].append("Unusual trading volume")
        if bars[-1]["volume"] == 0 or (ratio is not None and ratio < Decimal("0.2")):
            result["reasons"].append("Low observed trading activity")
        result["status"] = "elevated" if result["reasons"] else "no_anomaly_detected"
        result["evidence"] = {
            "daily_return_pct": (latest * 100).quantize(Decimal("0.000001")),
            "modified_z": score.quantize(Decimal("0.000001")),
            "volume_multiple": ratio.quantize(Decimal("0.000001")) if ratio is not None else None,
            "latest_close": bars[-1]["close"],
            "latest_volume": bars[-1]["volume"],
            "as_of": bars[-1]["as_of"],
            "source": history["source"],
        }
    return wire(result)


async def value_portfolio(conn, tenant, portfolio, now):
    rows = await conn.fetch(
        """SELECT market,symbol,currency,bool_or(is_demo) AS is_demo,
        sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END) AS quantity
        FROM saas.portfolio_transactions WHERE tenant_id=$1 AND portfolio_id=$2
        GROUP BY market,symbol,currency HAVING sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END)<>0
        ORDER BY market,symbol,currency LIMIT 501""",
        tenant,
        portfolio["id"],
    )
    if len(rows) > 500:
        raise ValueError("Interactive valuation is limited to 500 open positions")
    result = {
        "portfolio_id": portfolio["id"],
        "portfolio_version": portfolio["version"],
        "base_currency": portfolio["base_currency"],
        "evaluated_at": now,
        "method": "daily-close-v1",
        "status": "complete",
        "is_demo": False,
        "positions": [],
        "total_value": None,
        "valued_subtotal": Decimal(0),
    }
    with localcontext() as ctx:
        ctx.prec = 128
        for row in rows:
            p = {
                **dict(row),
                "status": "missing",
                "value": None,
                "base_value": None,
                "allocation_pct": None,
                "bar_id": None,
                "fx_id": None,
                "reason": "Listing or price unavailable",
            }
            result["is_demo"] |= p["is_demo"]
            instrument = await conn.fetchrow(
                "SELECT * FROM saas.instruments WHERE market=$1 AND symbol=$2 AND currency=$3",
                p["market"],
                p["symbol"],
                p["currency"],
            )
            if instrument:
                history = await load_history(conn, instrument, now, limit=1)
                p["status"], p["reason"] = history["quality"], history["reason"]
                if history["quality"] in {"demo", "end_of_day"}:
                    bar = history["bars"][-1]
                    p.update(
                        price=bar["close"],
                        bar_id=bar["id"],
                        price_as_of=bar["as_of"],
                        source=bar["source"],
                    )
                    p["value"] = p["quantity"] * bar["close"]
                    if p["currency"] == portfolio["base_currency"]:
                        p["base_value"] = p["value"]
                    else:
                        fx = await conn.fetchrow(
                            """SELECT * FROM saas.fx_rates WHERE base_currency=$1 AND quote_currency=$2
                            AND is_demo=$3 AND source=$4 AND as_of<=$5 ORDER BY as_of DESC LIMIT 1""",
                            p["currency"],
                            portfolio["base_currency"],
                            p["is_demo"],
                            bar["source"],
                            now,
                        )
                        if fx and (now - fx["as_of"]).total_seconds() <= 345600:
                            p.update(
                                fx_id=fx["id"],
                                fx_rate=fx["rate"],
                                fx_as_of=fx["as_of"],
                                base_value=p["value"] * fx["rate"],
                            )
                        else:
                            p.update(
                                status="missing_fx",
                                reason="No fresh direct FX rate from the selected source",
                            )
            if p["base_value"] is None:
                result["status"] = "incomplete"
            else:
                result["valued_subtotal"] += p["base_value"]
            result["positions"].append(p)
        if result["status"] == "complete":
            result["total_value"] = result["valued_subtotal"]
            if result["total_value"]:
                for p in result["positions"]:
                    p["allocation_pct"] = (p["base_value"] / result["total_value"] * 100).quantize(
                        Decimal("0.000001")
                    )
    return wire(result)
