import json
import logging
import zmq
import zmq.asyncio

logger = logging.getLogger("market_data.publisher")

class ZMQStreamPublisher:
    def __init__(self, endpoint: str, public_key: bytes | None = None, secret_key: bytes | None = None):
        self.endpoint = endpoint
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.PUB)

        if public_key and secret_key:
            self.socket.curve_server = True
            self.socket.curve_publickey = public_key
            self.socket.curve_secretkey = secret_key
            logger.info("CurveZMQ encryption initialized.")

    def start(self) -> None:
        self.socket.bind(self.endpoint)
        logger.info(f"ZMQ Publisher bound successfully to {self.endpoint}")

    async def publish(self, topic: str, payload: dict) -> None:
        serialized = json.dumps(payload)
        await self.socket.send_multipart([topic.encode("utf-8"), serialized.encode("utf-8")])

    def close(self) -> None:
        self.socket.close()
        self.context.term()