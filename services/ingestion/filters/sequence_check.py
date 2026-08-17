import logging
from typing import Optional, Dict, Any
from services.ingestion.filters.base import PipelineFilter
from services.logging_helpers import redact_symbol

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
                        logger.warning("Duplicate/out-of-order sequence dropped for %s: %s <= %s", redact_symbol(symbol), seq_id, last_seq)
                        return None
            if seq_id > last_seq + 1:
                        logger.warning("Sequence gap detected for %s: Expected %s, received %s", redact_symbol(symbol), last_seq + 1, seq_id)

        self._last_sequences[symbol] = seq_id
        return payload