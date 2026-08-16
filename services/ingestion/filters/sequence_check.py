import logging
from typing import Optional, Dict, Any
from services.ingestion.filters.base import PipelineFilter

logger = logging.getLogger("ingestion.filter.sequence")

class SequenceValidationFilter(PipelineFilter):
    def __init__(self):
        self._last_sequences: Dict[str, int] = {}

    async def filter(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        symbol = payload.get("s")
        seq_id = payload.get("t")  # Field for Trade ID/Sequence

        if not symbol or seq_id is None:
            return payload

        last_seq = self._last_sequences.get(symbol)
        if last_seq is not None:
            if seq_id <= last_seq:
                logger.warning(f"Duplicate/out-of-order sequence dropped for {symbol}: {seq_id} <= {last_seq}")
                return None
            if seq_id > last_seq + 1:
                logger.warning(f"Sequence gap detected for {symbol}: Expected {last_seq + 1}, received {seq_id}")

        self._last_sequences[symbol] = seq_id
        return payload