from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class PipelineFilter(ABC):
    @abstractmethod
    async def filter(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Processes frame through pipeline. Returns None if check fails."""
        pass