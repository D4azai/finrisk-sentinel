import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.api.settings import APISettings
from services.instruments.catalog import import_catalog, parse_catalog
from services.instruments.models import InstrumentRecord, InstrumentView, valid_isin
from services.instruments.providers import (
    DemoQuoteProvider,
    ProviderInfo,
    ProviderUnavailable,
    Quote,
    fetch_quote,
)

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def record(**changes):
    return dict(
        market="XCAS",
        symbol="TEST",
        currency="MAD",
        name="Test equity",
        isin="US0378331005",
        source="test fixture",
        verified_at="2026-01-01T00:00:00Z",
        **changes,
    )


def listing(**changes):
    values = record()
    values.update(changes)
    return InstrumentView(id=uuid4(), updated_at=NOW, **values)


@pytest.mark.parametrize("isin", ["US0378331005", "US5949181045", "GB0002634946"])
def test_isin_check_digit(isin):
    assert valid_isin(isin) == isin


@pytest.mark.parametrize("isin", ["US0378331006", "us0378331005", "US037833100", "US!378331005"])
def test_bad_isin(isin):
    with pytest.raises(ValueError):
        valid_isin(isin)


@pytest.mark.parametrize(
    "changes",
    [
        {"isin": None},
        {"market": "casablanca"},
        {"currency": "mad"},
        {"name": "\n"},
        {"verified_at": "2099-01-01T00:00:00Z"},
        {"verified_at": "2026-01-01T00:00:00"},
        {"is_demo": "false"},
    ],
)
def test_bad_reference_data(changes):
    with pytest.raises(ValidationError):
        InstrumentRecord.model_validate({**record(), **changes})


def test_import_rejects_duplicates_and_oversize():
    with pytest.raises(ValidationError, match="Duplicate"):
        parse_catalog(
            json.dumps({"schema_version": 1, "instruments": [record(), record()]}).encode()
        )
    with pytest.raises(ValueError, match="8 MiB"):
        parse_catalog(b" " * (8 * 1024 * 1024 + 1))


async def test_demo_import_rejected_before_database_access():
    conn = AsyncMock()
    raw = json.dumps({"schema_version": 1, "instruments": [{**record(), "is_demo": True}]}).encode()
    for environment, allow in [("production", True), ("development", False)]:
        with pytest.raises(ValueError, match="non-production"):
            await import_catalog(conn, raw, environment=environment, allow_demo=allow)
    assert not conn.mock_calls


def test_production_rejects_demo_provider_and_configuration():
    with pytest.raises(ValueError):
        DemoQuoteProvider(environment="production", enabled=True)
    with pytest.raises(ValueError):
        DemoQuoteProvider(environment="development", enabled=False)
    with pytest.raises(ValidationError, match="Demo market data"):
        APISettings(
            _env_file=None,
            _env_prefix="TEST_CATALOG_",
            environment="production",
            database_url="postgresql://u:p@host/db?sslmode=verify-full",
            oidc_issuer="https://identity.example",
            oidc_jwks_url="https://identity.example/jwks",
            allow_demo_market_data=True,
        )


class StubProvider:
    info = ProviderInfo(name="test-provider", markets=("XCAS",), mode="realtime")

    def __init__(self, quote):
        self.quote = quote

    async def get_quote(self, instrument):
        return self.quote


def quote_for(instrument, **changes):
    values = dict(
        instrument_id=instrument.id,
        provider="test-provider",
        currency="MAD",
        price="123.123456789012",
        as_of=NOW,
        received_at=NOW,
        mode="realtime",
        session="open",
    )
    return Quote(**{**values, **changes})


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "available"),
        ({"as_of": NOW - timedelta(minutes=6)}, "stale"),
        ({"currency": "USD"}, "invalid"),
        ({"instrument_id": uuid4()}, "invalid"),
        ({"provider": "wrong"}, "invalid"),
        ({"mode": "demo"}, "invalid"),
        ({"received_at": NOW + timedelta(seconds=10)}, "invalid"),
        ({"session": "unknown"}, "session_unknown"),
        ({"session": "closed"}, "market_closed"),
    ],
)
async def test_quote_quality_and_identity(changes, expected):
    instrument = listing()
    result = await fetch_quote(StubProvider(quote_for(instrument, **changes)), instrument, now=NOW)
    assert result.status == expected
    if expected == "invalid":
        assert result.quote is None
    else:
        assert result.quote.model_dump(mode="json")["price"] == "123.123456789012"


async def test_missing_unconfigured_and_delayed_quotes():
    instrument = listing()
    assert (await fetch_quote(None, instrument, now=NOW)).status == "not_configured"
    assert (await fetch_quote(StubProvider(None), instrument, now=NOW)).status == "missing"
    provider = StubProvider(quote_for(instrument, mode="delayed"))
    provider.info = ProviderInfo(name="test-provider", markets=("XCAS",), mode="delayed")
    assert (await fetch_quote(provider, instrument, now=NOW)).status == "delayed"


async def test_demo_never_impersonates_live_data():
    instrument = listing(is_demo=True, isin=None)
    provider = DemoQuoteProvider(environment="test", enabled=True)
    now = datetime.now(UTC)
    assert (await fetch_quote(provider, instrument, now=now)).status == "not_configured"
    result = await fetch_quote(provider, instrument, now=now, allow_demo=True)
    assert result.status == "demo" and result.quote.mode == "demo"
    assert result.quote.as_of == datetime(2026, 1, 1, tzinfo=UTC)
    assert (await fetch_quote(provider, listing(), now=now, allow_demo=True)).status == "missing"


async def test_provider_timeout_and_failure_are_explicit():
    class Slow(StubProvider):
        async def get_quote(self, instrument):
            await asyncio.sleep(1)

    class Failing(StubProvider):
        async def get_quote(self, instrument):
            raise ProviderUnavailable("sensitive upstream detail")

    for provider in [Slow(None), Failing(None)]:
        result = await fetch_quote(provider, listing(), now=NOW, timeout_seconds=0.01)
        assert result.status == "unavailable"
        assert "sensitive" not in result.model_dump_json()
