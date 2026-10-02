from uuid import uuid4

import pytest
from fastapi import HTTPException

from services.api.imports import MAX_IMPORT_ROWS, parse_transactions


def test_parse_csv_normalizes_and_generates_stable_request_ids():
    request_id = uuid4()
    text = (
        "market,symbol,currency,side,quantity,price,fees,executed_at\n"
        "xcas,test,mad,BUY,2.5,100,1,2026-01-01T12:00:00+00:00\n"
    )
    first = parse_transactions(text, request_id)
    second = parse_transactions(text, request_id)
    assert first[0]["errors"] == []
    assert first[0]["data"]["market"] == "XCAS"
    assert first[0]["data"]["side"] == "buy"
    assert first[0]["data"]["client_request_id"] == second[0]["data"]["client_request_id"]


@pytest.mark.parametrize(
    "text,message",
    [
        ("market,symbol\nXCAS,TEST\n", "missing"),
        (
            "market,symbol,currency,side,quantity,price,executed_at,unknown\n"
            "XCAS,TEST,MAD,buy,1,2,2026-01-01T00:00:00Z,x\n",
            "unexpected",
        ),
        ("", "header"),
    ],
)
def test_parse_csv_rejects_invalid_shape(text, message):
    with pytest.raises(HTTPException, match=message):
        parse_transactions(text, uuid4())


def test_parse_csv_has_synchronous_row_boundary():
    header = "market,symbol,currency,side,quantity,price,executed_at\n"
    row = "XCAS,TEST,MAD,buy,1,2,2026-01-01T00:00:00Z\n"
    with pytest.raises(HTTPException) as error:
        parse_transactions(header + row * (MAX_IMPORT_ROWS + 1), uuid4())
    assert error.value.status_code == 413
