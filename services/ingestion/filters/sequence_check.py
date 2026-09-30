from services.ingestion.filters.base import PipelineFilter


class SequenceValidationFilter(PipelineFilter):
    """Stateless shape validation; sequence tracking belongs to the database transaction."""

    async def filter(self, payload):
        symbol, sequence = payload.get("s"), payload.get("t")
        if not isinstance(symbol, str) or not symbol or type(sequence) is not int or sequence < 0:
            return None
        return payload
