from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.api.ledger_models import TransactionCreate


def payload(**changes):
    return dict(
        client_request_id=str(uuid4()),
        market="XCAS",
        symbol="TEST",
        currency="MAD",
        side="buy",
        quantity="0.123456789012",
        price="100",
        executed_at="2026-01-01T00:00:00Z",
        **changes,
    )


def test_exact_amounts_and_default_fees():
    value = TransactionCreate.model_validate(payload())
    assert value.quantity == Decimal("0.123456789012")
    assert value.fees == Decimal("0")
    assert value.model_dump(mode="json")["quantity"] == "0.123456789012"


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", 0.1),
        ("quantity", "0"),
        ("quantity", "NaN"),
        ("price", "Infinity"),
        ("fees", "-1"),
        ("quantity", "0.0000000000001"),
        ("price", "1000000000000000000"),
        ("market", "BAD"),
        ("symbol", "a:b"),
        ("executed_at", "2026-01-01T00:00:00"),
        ("executed_at", "2099-01-01T00:00:00Z"),
        ("tenant_id", str(uuid4())),
    ],
)
def test_invalid_trade(field, value):
    body = payload()
    body[field] = value
    with pytest.raises(ValidationError):
        TransactionCreate.model_validate(body)
