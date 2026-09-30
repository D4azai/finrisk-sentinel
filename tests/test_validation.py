import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest

from services.common.contracts import RawEnvelope, utcnow
from services.ingestion.config.settings import IngestionSettings
from services.ingestion.normalizers.base import CanonicalTrade
from services.ingestion.normalizers.binance_adapter import BinanceAdapter
from services.ingestion.processor import InvalidRecord, normalize_record


def trade_payload(sequence=1, **changes):
    now_ms = int(utcnow().timestamp() * 1000)
    return {
        "e": "trade",
        "s": "BTCUSDT",
        "p": "65000.123456789012345678",
        "q": "0.00000001",
        "t": sequence,
        "E": now_ms,
        "T": now_ms,
        **changes,
    }


def encoded(payload, **envelope_changes):
    return (
        RawEnvelope(payload_text=json.dumps(payload), **envelope_changes).model_dump_json().encode()
    )


@pytest.mark.parametrize(
    "value",
    [b"{", b"[]", b"null", b"\xff", None, b"x" * 524289],
    ids=["json", "array", "null", "utf8", "tombstone", "oversized"],
)
def test_bad_envelopes(value):
    with pytest.raises(InvalidRecord):
        normalize_record(value, IngestionSettings(_env_file=None))


@pytest.mark.parametrize(
    "changes",
    [
        {"p": "NaN"},
        {"q": "Infinity"},
        {"p": "-1"},
        {"p": 1.5},
        {"q": "0"},
        {"t": True},
        {"t": -1},
        {"T": "today"},
        {"T": None},
        {"s": "../x"},
        {"e": "depthUpdate"},
    ],
)
def test_invalid_trade_fields(changes):
    with pytest.raises(InvalidRecord):
        normalize_record(encoded(trade_payload(**changes)), IngestionSettings(_env_file=None))


def test_exact_decimals_and_schema():
    raw = encoded(trade_payload())
    result = normalize_record(raw, IngestionSettings(_env_file=None))
    assert result.price == Decimal("65000.123456789012345678")
    assert json.loads(result.model_dump_json())["volume"] == "1E-8"
    for name, value in [("raw.v1", json.loads(raw)), ("trade.v1", result.model_dump(mode="json"))]:
        schema = json.loads(Path(f"contracts/events/{name}.schema.json").read_text())
        jsonschema.validate(value, schema)


def test_replay_preserves_old_trade_with_late_flag():
    past = utcnow() - timedelta(days=10)
    value = encoded(
        trade_payload(T=int(past.timestamp() * 1000), E=int(past.timestamp() * 1000)),
        received_at=past,
    )
    result = normalize_record(value, IngestionSettings(_env_file=None))
    assert result.quality_flags == ("late",)


def test_future_high_id_is_rejected():
    future = int((utcnow() + timedelta(minutes=5)).timestamp() * 1000)
    with pytest.raises(InvalidRecord, match="future_source_time"):
        normalize_record(
            encoded(trade_payload(999999, T=future)), IngestionSettings(_env_file=None)
        )


def test_missing_required_field_rejected():
    payload = trade_payload()
    del payload["p"]
    with pytest.raises(InvalidRecord):
        normalize_record(encoded(payload), IngestionSettings(_env_file=None))


def test_decimal_precision_is_not_rounded():
    with pytest.raises(ValueError):
        BinanceAdapter().adapt(trade_payload(p="0.1234567890123456789"))


def test_large_sequence_roundtrips_as_string():
    result = BinanceAdapter().adapt(trade_payload(sequence=9223372036854775807))
    serialized = result.model_dump_json()
    assert json.loads(serialized)["sequence_id"] == "9223372036854775807"
    assert CanonicalTrade.model_validate_json(serialized) == result


def test_missing_envelope_version_is_not_silently_defaulted():
    value = json.loads(encoded(trade_payload()))
    del value["schema_version"]
    with pytest.raises(InvalidRecord, match="invalid_envelope"):
        normalize_record(json.dumps(value).encode(), IngestionSettings(_env_file=None))
