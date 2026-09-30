import base64

import websockets

from services.common.contracts import RawEnvelope
from services.market_data.connectors.base import BaseExchangeConnector


class BinanceWSConnector(BaseExchangeConnector):
    def __init__(self, symbols: list[str], max_payload_bytes=65536):
        self.symbols = [s.lower() for s in symbols]
        self.max_payload_bytes = max_payload_bytes
        stream_names = "/".join(f"{s}@trade" for s in self.symbols)
        self.url = f"wss://stream.binance.com:9443/stream?streams={stream_names}"

    async def connect_and_stream(self):
        async with websockets.connect(
            self.url,
            ping_interval=20,
            ping_timeout=10,
            open_timeout=10,
            close_timeout=5,
            max_size=self.max_payload_bytes,
            max_queue=16,
        ) as websocket:
            async for message in websocket:
                # Preserve malformed JSON for durable quarantine downstream.
                if isinstance(message, bytes):
                    yield RawEnvelope(
                        payload_text=base64.b64encode(message).decode("ascii"),
                        payload_encoding="base64",
                    )
                else:
                    yield RawEnvelope(payload_text=message)
