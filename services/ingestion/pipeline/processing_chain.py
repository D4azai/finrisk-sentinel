import logging
from typing import List, Optional, Dict, Any
from services.ingestion.filters.base import PipelineFilter

logger = logging.getLogger("ingestion.pipeline")

class IngestionPipeline:
    def __init__(self, filters: List[PipelineFilter]):
        self._filters = filters

    async def execute(self, raw_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = raw_payload
        for pipe in self._filters:
            current = await pipe.filter(current)
            if current is None:
                return None
        return current