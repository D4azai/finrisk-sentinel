import base64
import json

from pydantic import ValidationError

from services.common.contracts import RawEnvelope, utcnow
from services.ingestion.normalizers.binance_adapter import BinanceAdapter


class InvalidRecord(ValueError):
    pass


def normalize_record(value, settings, max_bytes=65536, now=None):
    now = now or utcnow()
    # Envelope escaping may expand the source by several times.
    if not isinstance(value, bytes) or len(value) > max_bytes * 8:
        raise InvalidRecord("oversized_envelope")
    try:
        document = json.loads(value)
        required = {
            "schema_version",
            "event_id",
            "exchange",
            "market_type",
            "received_at",
            "payload_text",
        }
        if not isinstance(document, dict) or not required.issubset(document):
            raise InvalidRecord("invalid_envelope")
        envelope = RawEnvelope.model_validate_json(value)
        payload_bytes = (
            base64.b64decode(envelope.payload_text, validate=True)
            if envelope.payload_encoding == "base64"
            else envelope.payload_text.encode("utf-8")
        )
        if len(payload_bytes) > max_bytes:
            raise InvalidRecord("oversized_payload")
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise InvalidRecord("invalid_payload_shape")
        payload = payload.get("data", payload)
        if not isinstance(payload, dict):
            raise InvalidRecord("invalid_payload_shape")
        trade = BinanceAdapter().adapt(payload, received_at=envelope.received_at, now=now)
    except (ValidationError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, InvalidRecord):
            raise
        raise InvalidRecord("invalid_trade_payload") from None
    # Compare exchange time to receive time so replay is independent of wall clock.
    skew = settings.max_future_skew_sec
    if envelope.received_at > now and (envelope.received_at - now).total_seconds() > skew:
        raise InvalidRecord("future_receive_time")
    if any(
        (stamp - envelope.received_at).total_seconds() > skew
        for stamp in (trade.timestamp, trade.source_event_at)
    ):
        raise InvalidRecord("future_source_time")
    late = (now - min(trade.timestamp, trade.source_event_at)).total_seconds()
    if late > settings.max_allowed_staleness_sec:
        trade = trade.model_copy(update={"quality_flags": ("late",)})
    return trade


async def process_record(store, record, settings, *, on_fresh=None):
    try:
        trade = normalize_record(record.value, settings, store.settings.max_payload_bytes)
    except InvalidRecord as exc:
        return await store.process(record, rejection=str(exc))
    outcome = await store.process(record, trade=trade)
    if outcome == "accepted" and "late" not in trade.quality_flags and on_fresh:
        on_fresh()
    return outcome
