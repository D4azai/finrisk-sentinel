from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


def utcnow():
    return datetime.now(timezone.utc)


class RawEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    exchange: Literal["binance"] = "binance"
    market_type: Literal["spot"] = "spot"
    received_at: AwareDatetime = Field(default_factory=utcnow)
    payload_encoding: Literal["utf8", "base64"] = "utf8"
    payload_text: str = Field(max_length=87384)
