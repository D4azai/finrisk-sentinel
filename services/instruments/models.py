import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


def valid_isin(value: str) -> str:
    """Check ISO 6166 shape and modulus-10 check digit, not allocation authenticity."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
        raise ValueError("ISIN must contain two letters, nine alphanumerics, and a check digit")
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in value)
    total = 0
    for index, digit in enumerate(reversed(digits)):
        number = int(digit) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    if total % 10:
        raise ValueError("Invalid ISIN check digit")
    return value


class InstrumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    market: str = Field(pattern=r"^[A-Z0-9]{4}$")
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=160, pattern=r"^[^\x00-\x1f\x7f]+$")
    isin: str | None = None
    asset_class: Literal["equity"] = "equity"
    is_demo: bool = Field(default=False, strict=True)
    active: bool = Field(default=True, strict=True)
    source: str = Field(min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")
    verified_at: AwareDatetime

    @field_validator("isin")
    @classmethod
    def check_isin(cls, value):
        return valid_isin(value) if value is not None else value

    @field_validator("verified_at")
    @classmethod
    def checked_in_past(cls, value):
        if value > datetime.now(UTC):
            raise ValueError("Reference-data verification cannot be in the future")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_identifier(self):
        if not self.is_demo and self.isin is None:
            raise ValueError("Non-demo equities require an ISIN")
        return self


class CatalogImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    instruments: list[InstrumentRecord] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique_listings(self):
        keys = [(item.market, item.symbol, item.currency) for item in self.instruments]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate listing in catalog import")
        return self


class InstrumentView(InstrumentRecord):
    id: UUID
    updated_at: datetime


class InstrumentPage(BaseModel):
    items: list[InstrumentView]
    next_cursor: UUID | None
