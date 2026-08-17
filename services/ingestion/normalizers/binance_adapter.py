import logging
from datetime import datetime, timezone
from services.ingestion.normalizers.base import BaseAdapter, CanonicalTrade
from services.logging_helpers import redact_payload

logger = logging.getLogger("ingestion.adapter.binance")

class BinanceAdapter(BaseAdapter):
    def adapt(self, raw_payload: dict) -> CanonicalTrade | None:
        try:
            return CanonicalTrade(
                symbol=str(raw_payload["s"]).upper(),
                exchange="binance",
                price=float(raw_payload["p"]),
                volume=float(raw_payload["q"]),
                sequence_id=int(raw_payload["t"]),
                timestamp=datetime.fromtimestamp(raw_payload["T"] / 1000.0, tz=timezone.utc)
            )
        except (KeyError, ValueError, TypeError) as err:
            logger.error("Failed to normalize Binance payload: %s | Payload: %s", err, redact_payload(raw_payload))
            return None