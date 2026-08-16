from datetime import datetime, timezone
from services.ingestion.normalizers.base import BaseAdapter, CanonicalTrade

class BinanceAdapter(BaseAdapter):
    def adapt(self, raw_payload: dict) -> CanonicalTrade:
        return CanonicalTrade(
            symbol=raw_payload["s"].upper(),
            exchange="binance",
            price=float(raw_payload["p"]),
            volume=float(raw_payload["q"]),
            sequence_id=int(raw_payload["t"]),  # Binance Trade ID
            timestamp=datetime.fromtimestamp(raw_payload["T"] / 1000, tz=timezone.utc)
        )