"""Contract and synthetic-data tests for optional statistical research module."""
import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from services.analytics.statistical_research import analyze_time_series


def history(count=110):
    start = date(2025, 1, 1)
    bars = [
        {
            "session_date": start + timedelta(days=i),
            "close": Decimal(str(100 + i * 0.12 + 0.25 * math.sin(2 * math.pi * i / 5))),
            "adjusted": True,
            "is_demo": True,
        }
        for i in range(count)
    ]
    return {"quality": "demo", "source": "synthetic-test", "bars": bars}


@pytest.mark.parametrize("model", ["arima", "sarima"])
def test_time_series_research_has_forecast_and_honest_baseline(model):
    pytest.importorskip("statsmodels")
    report = analyze_time_series(history(), model=model, horizon=3, folds=2)
    assert report["model"] == model.upper()
    assert report["data"]["is_demo"] is True
    assert len(report["forecast"]) == 3
    assert report["backtest"]["folds"] == 2
    assert report["backtest"]["naive_mae"] >= 0
    assert all(item["lower_95"] <= item["upper_95"] for item in report["forecast"])
    assert "candidate_date" in report["structural_break"]


def test_time_series_rejects_bad_quality_gaps_and_unadjusted_data():
    h = history()
    h["quality"] = "gap"
    with pytest.raises(ValueError, match="complete"):
        analyze_time_series(h)
    h = history()
    h["bars"][8]["adjusted"] = False
    with pytest.raises(ValueError, match="adjusted"):
        analyze_time_series(h)
    h = history()
    h["bars"][8]["session_date"] = h["bars"][7]["session_date"]
    with pytest.raises(ValueError, match="increasing"):
        analyze_time_series(h)


def test_time_series_rejects_invalid_parameters_and_short_history():
    with pytest.raises(ValueError, match="model"):
        analyze_time_series(history(), model="other")
    with pytest.raises(ValueError, match="Out-of-range"):
        analyze_time_series(history(), horizon=99)
    with pytest.raises(ValueError, match="90"):
        analyze_time_series(history(40))
