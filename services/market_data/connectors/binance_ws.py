import json
import logging
import websockets
from typing import AsyncGenerator, Dict, Any
from services.market_data.connectors.base import BaseExchangeConnector

logger = logging.getLogger("market_data.binance")

class BinanceWSConnector(BaseExchangeConnector):
    def __init__(self, symbols: list[str]):
        self.symbols = [s.lower() for s in symbols]
        stream_names = "/".join([f"{s}@trade" for s in self.symbols])
        self.url = f"wss://stream.binance.com:9443/stream?streams={stream_names}"

    async def connect_and_stream(self) -> AsyncGenerator[Dict[str, Any], None]:
        logger.info(f"Connecting to Binance WebSocket URL: {self.url}")
        async with websockets.connect(self.url, ping_interval=20, ping_timeout=10) as ws:
            async for message in ws:
                data = json.loads(message)
                if "data" in data:
                    yield data["data"]