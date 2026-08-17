import json
import logging
import websockets
from typing import AsyncGenerator, Dict, Any

from services.market_data.connectors import ConnectorFactory
from services.market_data.connectors.base import BaseExchangeConnector
from services.logging_helpers import redact_symbol

logger = logging.getLogger("market_data.binance")

@ConnectorFactory.register("binance")
class BinanceWSConnector(BaseExchangeConnector):
    def __init__(self, symbols: list[str]):
        self.symbols = [s.lower() for s in symbols]
        stream_names = "/".join([f"{s}@trade" for s in self.symbols])
        self.url = f"wss://stream.binance.com:9443/stream?streams={stream_names}"

    async def connect_and_stream(self) -> AsyncGenerator[Dict[str, Any], None]:
        # Avoid logging full URL (may contain subscribed symbols). Log counts and sample obfuscated symbol instead.
        sample = self.symbols[0] if self.symbols else None
        logger.info("Connecting to Binance WebSocket (exchange=binance, streams=%d, sample=%s)", len(self.symbols), redact_symbol(sample))
        async with websockets.connect(
            self.url,
            ping_interval=20,
            ping_timeout=10,
            max_size=10_000_000  # Prevent memory buffer overflow on high volatility
        ) as ws:
            async for message in ws:
                try:
                    data = json.loads(message)
                    if isinstance(data, dict) and "data" in data:
                        yield data["data"]
                except json.JSONDecodeError:
                    logger.error(f"Malformed WS frame received: {message[:100]!r}")
                except Exception as err:
                    logger.error(f"Unexpected error processing WS message: {err}")