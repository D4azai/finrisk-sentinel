import json
import logging
import zmq
import zmq.asyncio
from services.ingestion.normalizers.base import CanonicalTrade

logger = logging.getLogger("ingestion.publisher")

class CleanStreamPublisher:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.PUB)

    def start(self) -> None:
        self.socket.bind(self.endpoint)
        logger.info(f"Clean Stream Publisher bound to {self.endpoint}")

    async def publish(self, trade: CanonicalTrade) -> None:
        topic = f"clean.{trade.symbol.lower()}"
        payload_bytes = trade.model_dump_json().encode("utf-8")
        await self.socket.send_multipart([topic.encode("utf-8"), payload_bytes])

    def close(self) -> None:
        self.socket.close()
        self.context.term()