import re
from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, Field


def decimal_string(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,18}(\.[0-9]{1,12})?", value):
        raise ValueError("Use a decimal string with at most 18 integer and 12 fractional digits")
    return value


Amount = Annotated[
    Decimal,
    BeforeValidator(decimal_string, json_schema_input_type=str),
    Field(ge=0, lt=Decimal("1e18"), max_digits=30, decimal_places=12, allow_inf_nan=False),
]
