import json
from decimal import ROUND_CEILING, Decimal, localcontext
from hashlib import sha256

from services.analytics.engine import load_history, value_portfolio, wire

MINIMUM_OBSERVATIONS = 30
METHOD_VERSION = "current-weight-historical-v1"


def _q(value):
    return value.quantize(Decimal("0.000001")) if value is not None else None


def _sample_stddev(values):
    if len(values) < 2:
        return None
    with localcontext() as ctx:
        ctx.prec = 128
        mean = sum(values, Decimal(0)) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        return variance.sqrt()


def summarize_historical_risk(asset_returns, weights, confidence):
    """Summarize aligned daily asset returns using fixed current portfolio weights."""
    if not asset_returns or set(asset_returns) != set(weights):
        return None
    common_dates = set.intersection(*(set(series) for series in asset_returns.values()))
    if len(common_dates) < MINIMUM_OBSERVATIONS:
        return None
    dates = sorted(common_dates)
    with localcontext() as ctx:
        ctx.prec = 128
        returns = [
            sum((weights[key] * asset_returns[key][day] for key in weights), Decimal(0))
            for day in dates
        ]
        tail_count = max(
            1,
            int(
                (Decimal(len(returns)) * (Decimal(1) - confidence)).to_integral_value(
                    rounding=ROUND_CEILING
                )
            ),
        )
        ordered = sorted(returns)
        threshold = ordered[tail_count - 1]
        value_at_risk = max(Decimal(0), -threshold)
        expected_shortfall = max(Decimal(0), -sum(ordered[:tail_count], Decimal(0)) / tail_count)
        daily_volatility = _sample_stddev(returns)
        annual_volatility = daily_volatility * Decimal(252).sqrt()
        individual_volatility = {
            key: _sample_stddev([asset_returns[key][day] for day in dates]) for key in weights
        }
        weighted_individual_volatility = sum(
            (abs(weights[key]) * (individual_volatility[key] or Decimal(0)) for key in weights),
            Decimal(0),
        )
        diversification_ratio = (
            weighted_individual_volatility / daily_volatility
            if daily_volatility and daily_volatility > 0
            else None
        )
        portfolio_mean = sum(returns, Decimal(0)) / len(returns)
        portfolio_variance = daily_volatility**2
        asset_statistics = {}
        for key in weights:
            values = [asset_returns[key][day] for day in dates]
            asset_mean = sum(values, Decimal(0)) / len(values)
            asset_volatility = individual_volatility[key]
            covariance = sum(
                (
                    (asset_value - asset_mean) * (portfolio_value - portfolio_mean)
                    for asset_value, portfolio_value in zip(values, returns)
                ),
                Decimal(0),
            ) / (len(values) - 1)
            correlation = (
                covariance / (asset_volatility * daily_volatility)
                if asset_volatility and daily_volatility
                else None
            )
            risk_contribution = (
                weights[key] * covariance / portfolio_variance * 100 if portfolio_variance else None
            )
            asset_statistics[key] = {
                "annualized_volatility_pct": _q(asset_volatility * Decimal(252).sqrt() * 100),
                "correlation_to_portfolio": _q(correlation),
                "volatility_contribution_pct": _q(risk_contribution),
            }
        wealth = peak = Decimal(1)
        max_drawdown = Decimal(0)
        for value in returns:
            wealth *= Decimal(1) + value
            peak = max(peak, wealth)
            if peak > 0:
                max_drawdown = max(max_drawdown, Decimal(1) - wealth / peak)
        downside_count = sum(value < 0 for value in returns)
        return {
            "observation_count": len(returns),
            "from_date": dates[0],
            "through_date": dates[-1],
            "annualized_volatility_pct": _q(annual_volatility * 100),
            "max_drawdown_pct": _q(max_drawdown * 100),
            "value_at_risk_pct": _q(value_at_risk * 100),
            "expected_shortfall_pct": _q(expected_shortfall * 100),
            "worst_day_pct": _q(min(returns) * 100),
            "best_day_pct": _q(max(returns) * 100),
            "downside_frequency_pct": _q(Decimal(downside_count) / len(returns) * 100),
            "diversification_ratio": _q(diversification_ratio),
            "tail_observation_count": tail_count,
            "asset_statistics": asset_statistics,
        }


def _scenario(scenario_id, name, description, shocks, positions, total):
    impact = sum(
        (
            Decimal(str(position["base_value"])) * shocks.get(str(position["instrument_id"]), 0)
            for position in positions
        ),
        Decimal(0),
    )
    return {
        "id": scenario_id,
        "name": name,
        "description": description,
        "estimated_impact": _q(impact),
        "estimated_impact_pct": _q(impact / total * 100) if total else None,
    }


async def analyze_portfolio_risk(conn, tenant, portfolio, now, confidence, lookback):
    valuation = await value_portfolio(conn, tenant, portfolio, now)
    result = {
        "portfolio_id": portfolio["id"],
        "portfolio_version": portfolio["version"],
        "base_currency": portfolio["base_currency"],
        "evaluated_at": now,
        "method_version": METHOD_VERSION,
        "status": "insufficient_data",
        "parameters": {
            "confidence": confidence,
            "lookback_sessions": lookback,
            "minimum_observations": MINIMUM_OBSERVATIONS,
            "annualization_sessions": 252,
        },
        "metrics": None,
        "concentration": None,
        "scenarios": [],
        "coverage": [],
        "limitations": [],
        "data_fingerprint": None,
    }
    positions = valuation["positions"]
    if valuation["status"] != "complete" or valuation["total_value"] is None:
        result["limitations"].append(
            "A complete current valuation, including required FX conversion, is needed."
        )
        return wire(result)
    total = Decimal(str(valuation["total_value"]))
    if total <= 0 or not positions:
        result["limitations"].append(
            "The portfolio needs a positive net value and an open position."
        )
        return wire(result)

    returns_by_asset = {}
    weights = {}
    fingerprint_positions = []
    incomplete_history = False
    foreign_currency = False
    for position in positions:
        instrument_id = str(position.get("instrument_id") or "")
        instrument = await conn.fetchrow(
            "SELECT * FROM saas.instruments WHERE id=$1", position.get("instrument_id")
        )
        if not instrument:
            incomplete_history = True
            result["coverage"].append(
                {"symbol": position["symbol"], "quality": "missing", "observations": 0}
            )
            continue
        history = await load_history(conn, instrument, now, limit=lookback + 1)
        bars = history["bars"]
        usable = history["quality"] in {"demo", "end_of_day"} and len(bars) >= 2
        usable = usable and all(bar["adjusted"] for bar in bars)
        series = {}
        if usable:
            for previous, current in zip(bars, bars[1:]):
                series[current["session_date"]] = current["close"] / previous["close"] - 1
        if len(series) < MINIMUM_OBSERVATIONS:
            incomplete_history = True
        returns_by_asset[instrument_id] = series
        weights[instrument_id] = Decimal(str(position["base_value"])) / total
        foreign_currency |= position["currency"] != portfolio["base_currency"]
        result["coverage"].append(
            {
                "instrument_id": instrument_id,
                "market": position["market"],
                "symbol": position["symbol"],
                "currency": position["currency"],
                "source": history["source"],
                "quality": history["quality"],
                "observations": len(series),
                "reason": history["reason"],
            }
        )
        fingerprint_positions.append(
            {
                "instrument_id": instrument_id,
                "weight": format(weights[instrument_id], "f"),
                "bar_ids": [str(bar["id"]) for bar in bars],
            }
        )

    if incomplete_history:
        result["limitations"].append(
            f"Every open position needs at least {MINIMUM_OBSERVATIONS} complete adjusted daily returns."
        )
    metrics = summarize_historical_risk(returns_by_asset, weights, confidence)
    if metrics is None:
        result["limitations"].append(
            f"At least {MINIMUM_OBSERVATIONS} dates shared by every position are required."
        )
        return wire(result)

    gross = sum((abs(Decimal(str(position["base_value"]))) for position in positions), Decimal(0))
    exposure_weights = [abs(Decimal(str(position["base_value"]))) / gross for position in positions]
    hhi = sum((weight * weight for weight in exposure_weights), Decimal(0))
    largest_index = max(range(len(positions)), key=lambda index: exposure_weights[index])
    result["metrics"] = metrics
    asset_statistics = result["metrics"].pop("asset_statistics")
    result["attribution"] = [
        {
            "instrument_id": str(position["instrument_id"]),
            "market": position["market"],
            "symbol": position["symbol"],
            "weight_pct": _q(weights[str(position["instrument_id"])] * 100),
            **asset_statistics[str(position["instrument_id"])],
        }
        for position in positions
    ]
    result["concentration"] = {
        "herfindahl_index": _q(hhi),
        "effective_holdings": _q(Decimal(1) / hhi) if hhi else None,
        "largest_position": positions[largest_index]["symbol"],
        "largest_position_pct": _q(exposure_weights[largest_index] * 100),
        "gross_exposure": _q(gross),
        "net_value": _q(total),
    }
    all_ids = {str(position["instrument_id"]) for position in positions}
    largest_id = str(positions[largest_index]["instrument_id"])
    foreign_ids = {
        str(position["instrument_id"])
        for position in positions
        if position["currency"] != portfolio["base_currency"]
    }
    result["scenarios"] = [
        _scenario(
            "broad-market-10",
            "Broad market decline",
            "Every current position declines 10%.",
            {key: Decimal("-0.10") for key in all_ids},
            positions,
            total,
        ),
        _scenario(
            "severe-market-20",
            "Severe market decline",
            "Every current position declines 20%.",
            {key: Decimal("-0.20") for key in all_ids},
            positions,
            total,
        ),
        _scenario(
            "largest-position-25",
            "Largest position shock",
            "The largest current exposure declines 25%.",
            {largest_id: Decimal("-0.25")},
            positions,
            total,
        ),
        _scenario(
            "foreign-currency-10",
            "Foreign-currency depreciation",
            f"Foreign position currencies depreciate 10% against {portfolio['base_currency']}.",
            {key: Decimal("-0.10") for key in foreign_ids},
            positions,
            total,
        ),
    ]
    result["limitations"].append(
        "Historical simulation uses current fixed weights and does not forecast future returns."
    )
    result["limitations"].append(
        "Stress scenarios are deterministic illustrations; they do not assign probabilities."
    )
    if foreign_currency:
        result["limitations"].append(
            "Historical FX returns are excluded; foreign positions use the latest accepted FX conversion."
        )
        result["status"] = "limited"
    else:
        result["status"] = "complete"
    fingerprint_input = {
        "method": METHOD_VERSION,
        "portfolio_version": portfolio["version"],
        "confidence": format(confidence, "f"),
        "lookback": lookback,
        "positions": sorted(fingerprint_positions, key=lambda item: item["instrument_id"]),
    }
    result["data_fingerprint"] = sha256(
        json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return wire(result)
