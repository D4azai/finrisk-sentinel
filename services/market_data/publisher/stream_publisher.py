import json
import logging
import zmq
import zmq.asyncio

logger = logging.getLogger("market_data.publisher")

class ZMQStreamPublisher:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.PUB)

    def start(self) -> None:
        self.socket.bind(self.endpoint)
        logger.info(f"ZMQ Publisher bound successfully to {self.endpoint}")

    async def publish(self, topic: str, payload: dict) -> None:
        serialized = json.dumps(payload)
        await self.socket.send_multipart([topic.encode("utf-8"), serialized.encode("utf-8")])

    def close(self) -> None:
        self.socket.close()
        self.context.term()