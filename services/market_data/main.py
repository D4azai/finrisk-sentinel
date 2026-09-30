import asyncio
import base64
import json
from contextlib import AsyncExitStack, aclosing
from uuid import uuid4

from services.common.broker import dispatch_forever, make_producer
from services.common.runtime import Health, bounded_close, run, supervise
from services.common.settings import InfrastructureSettings
from services.common.store import Backpressure, Store
from services.market_data.config.settings import MarketDataSettings
from services.market_data.connectors.factory import ConnectorFactory
from services.market_data.engine.connection_manager import ResilientConnectionManager


def routing_key(envelope):
    try:
        payload = (
            base64.b64decode(envelope.payload_text, validate=True).decode("utf-8")
            if envelope.payload_encoding == "base64"
            else envelope.payload_text
        )
        message = json.loads(payload)
        symbol = message.get("data", message)["s"]
        if isinstance(symbol, str) and symbol.isascii() and symbol.isalnum() and len(symbol) <= 30:
            return f"{envelope.exchange}:{envelope.market_type}:{symbol.upper()}"
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        pass
    return "invalid"


async def main():
    infrastructure, config = InfrastructureSettings(), MarketDataSettings()
    health = Health(infrastructure)
    async with AsyncExitStack() as stack:
        store = await Store.open(infrastructure)
        stack.push_async_callback(bounded_close, store.close)
        instruments = [f"{config.exchange_name}:spot:{symbol.upper()}" for symbol in config.symbols]
        owner = await stack.enter_async_context(store.collector_ownership(instruments))
        producer = make_producer(infrastructure)
        stack.push_async_callback(bounded_close, producer.stop)
        await producer.start()
        stack.push_async_callback(health.close)
        await health.start()
        connector = ConnectorFactory.create(config.exchange_name, config.symbols)
        connector.max_payload_bytes = infrastructure.max_payload_bytes

        async def interrupted(reason):
            await store.feed_interruption(owner, str(uuid4()), instruments, reason)
            health.last_frame = 0
            health.failures.labels("feed_interruption").inc()

        await interrupted("collector_start_or_restart")
        manager = ResilientConnectionManager(
            base_delay=config.base_reconnect_delay_sec,
            max_delay=config.max_reconnect_delay_sec,
            max_attempts=config.max_reconnect_attempts,
            idle_timeout=config.idle_timeout_sec,
            on_disconnect=interrupted,
        )

        async def collect():
            async with aclosing(manager.stream_with_retry(connector.connect_and_stream)) as stream:
                async for envelope in stream:
                    while True:
                        try:
                            await store.archive_raw(owner, envelope, routing_key(envelope))
                            break
                        except Backpressure:
                            health.last_frame = 0
                            await asyncio.sleep(1)
                    health.received.inc()
                    health.touch()

        await supervise(
            collect(),
            dispatch_forever(
                store, producer, [infrastructure.raw_topic, infrastructure.quality_topic], health
            ),
            health.watch(store),
        )


if __name__ == "__main__":
    run(main)
