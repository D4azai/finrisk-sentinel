from datetime import date, timedelta
from decimal import Decimal

from services.analytics.portfolio_risk import summarize_historical_risk


def series(values, start=date(2026, 1, 1)):
    return {start + timedelta(days=index): Decimal(value) for index, value in enumerate(values)}


def test_historical_risk_aligns_assets_and_measures_tail_loss():
    first = ["0.01", "-0.02", "0.005", "-0.01"] * 10
    second = ["0.002", "-0.01", "0.003", "-0.004"] * 10
    result = summarize_historical_risk(
        {"a": series(first), "b": series(second)},
        {"a": Decimal("0.6"), "b": Decimal("0.4")},
        Decimal("0.95"),
    )
    assert result["observation_count"] == 40
    assert result["tail_observation_count"] == 2
    assert result["expected_shortfall_pct"] >= result["value_at_risk_pct"] > 0
    assert result["annualized_volatility_pct"] > 0
    assert result["max_drawdown_pct"] > 0
    assert result["diversification_ratio"] >= 1
    contribution = sum(
        item["volatility_contribution_pct"] for item in result["asset_statistics"].values()
    )
    assert abs(contribution - Decimal("100")) < Decimal("0.00001")


def test_historical_risk_requires_thirty_shared_dates():
    first = series(["0.01"] * 40)
    shifted = series(["0.01"] * 40, start=date(2026, 2, 1))
    assert (
        summarize_historical_risk(
            {"a": first, "b": shifted},
            {"a": Decimal("0.5"), "b": Decimal("0.5")},
            Decimal("0.95"),
        )
        is None
    )


def test_historical_risk_rejects_missing_weight_or_series():
    assert (
        summarize_historical_risk(
            {"a": series(["0.01"] * 31)},
            {"b": Decimal("1")},
            Decimal("0.95"),
        )
        is None
    )
