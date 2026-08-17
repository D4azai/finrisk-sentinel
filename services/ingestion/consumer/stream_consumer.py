import json
import logging
import zmq
import zmq.asyncio
from typing import AsyncGenerator, Tuple, Dict, Any

logger = logging.getLogger("ingestion.consumer")

class ZMQStreamConsumer:
    def __init__(self, endpoint: str, subscriptions: list[str] | None = None, server_public_key: str | None = None):
        self.endpoint = endpoint
        self.subscriptions = subscriptions or [""]
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)

        if server_public_key:
            client_pub, client_sec = zmq.curve_keypair()
            self.socket.curve_secretkey = client_sec
            self.socket.curve_publickey = client_pub
            self.socket.curve_serverkey = server_public_key.encode("utf-8")

    def start(self) -> None:
        self.socket.connect(self.endpoint)
        for sub in self.subscriptions:
            self.socket.setsockopt_string(zmq.SUBSCRIBE, sub)
        logger.info(f"ZMQ Consumer connected to {self.endpoint}")

    async def listen(self) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
        while True:
            topic, payload_bytes = await self.socket.recv_multipart()
            data = json.loads(payload_bytes.decode("utf-8"))
            yield topic.decode("utf-8"), data

    def close(self) -> None:
        self.socket.close()
        self.context.term()