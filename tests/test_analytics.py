import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.analytics.engine import detect_anomalies, wire
from services.analytics.market import MarketImport


def observations():
    return {
        "quality": "end_of_day",
        "reason": "completed bars",
        "source": "test",
        "bars": [
            {
                "id": uuid4(),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
                "adjusted": True,
                "is_demo": False,
                "as_of": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i),
            }
            for i in range(31)
        ],
    }


def test_detector_is_quiet_on_stable_series_and_explains_joint_spike():
    h = observations()
    assert detect_anomalies(h)["status"] == "no_anomaly_detected"
    h["bars"][-1].update(close=Decimal("120"), volume=Decimal("9000"))
    signal = detect_anomalies(h)
    assert signal["status"] == "elevated"
    assert signal["reasons"] == ["Unusual daily price move", "Unusual trading volume"]
    assert signal["evidence"]["daily_return_pct"] == "20.000000"
    assert signal["evidence"]["volume_multiple"] == "9.000000"
    assert len(signal["bar_ids"]) == 31


@pytest.mark.parametrize("quality", ["missing", "stale", "gap", "calendar_unknown"])
def test_detector_refuses_bad_quality(quality):
    h = observations()
    h["quality"] = quality
    assert detect_anomalies(h)["status"] == "insufficient_data"


def test_short_history_unadjusted_splits_and_zero_volume():
    h = observations()
    h["bars"].pop()
    assert detect_anomalies(h)["status"] == "insufficient_data"
    h = observations()
    h["bars"][-1].update(close=Decimal("50"), adjusted=False)
    assert detect_anomalies(h)["status"] == "insufficient_data"
    h = observations()
    h["bars"][-1]["volume"] = Decimal(0)
    assert "Low observed trading activity" in detect_anomalies(h)["reasons"]


def market_payload():
    return {
        "source": "test",
        "is_demo": True,
        "sessions": [
            {
                "market": "XCAS",
                "session_date": "2026-01-01",
                "opens_at": "2026-01-01T09:00:00Z",
                "closes_at": "2026-01-01T16:00:00Z",
            }
        ],
        "bars": [
            {
                "market": "XCAS",
                "symbol": "TEST",
                "currency": "MAD",
                "session_date": "2026-01-01",
                "as_of": "2026-01-01T16:00:00Z",
                "open": "100",
                "high": "110",
                "low": "90",
                "close": "101",
                "volume": "1000",
                "adjusted": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"low": "105"},
        {"high": "95"},
        {"close": "NaN"},
        {"close": 101.1},
        {"volume": "-1"},
        {"as_of": "2099-01-01T16:00:00Z"},
        {"adjusted": "true"},
    ],
)
def test_market_validation(changes):
    p = market_payload()
    p["bars"][0].update(changes)
    with pytest.raises(ValidationError):
        MarketImport.model_validate(p)


def test_market_duplicate_and_decimal_wire():
    p = market_payload()
    p["bars"].append(p["bars"][0])
    with pytest.raises(ValidationError, match="Duplicate"):
        MarketImport.model_validate(p)
    value = Decimal("999999999999999999.123456789012")
    assert json.loads(json.dumps(wire({"value": value})))["value"] == str(value)
