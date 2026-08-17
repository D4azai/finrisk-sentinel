import asyncio
import logging
import signal
from services.market_data.config.settings import settings
from services.market_data.connectors import ConnectorFactory
from services.market_data.engine.connection_manager import ResilientConnectionManager
from services.market_data.publisher.stream_publisher import ZMQStreamPublisher

from services.logging_config import configure_app_logging

configure_app_logging()
logger = logging.getLogger("market_data.main")


async def shutdown(loop: asyncio.AbstractEventLoop, publisher: ZMQStreamPublisher):
    logger.info("Executing graceful service shutdown...")
    publisher.close()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


async def main():
    loop = asyncio.get_running_loop()

    pub_key = settings.zmq_public_key.encode("utf-8") if settings.zmq_public_key else None
    sec_key = settings.zmq_secret_key.encode("utf-8") if settings.zmq_secret_key else None

    publisher = ZMQStreamPublisher(endpoint=settings.zmq_pub_endpoint, public_key=pub_key, secret_key=sec_key)
    publisher.start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(loop, publisher)))

    connector = ConnectorFactory.create(settings.exchange_name, settings.symbols)
    manager = ResilientConnectionManager(
        base_delay=settings.base_reconnect_delay_sec,
        max_delay=settings.max_reconnect_delay_sec
    )

    logger.info(f"Market Data Service initialized for '{settings.exchange_name}'. Running stream...")

    async for raw_payload in manager.stream_with_retry(connector.connect_and_stream):
        topic = raw_payload.get("s", "market_data").lower()
        await publisher.publish(topic=topic, payload=raw_payload)


if __name__ == "__main__":
    asyncio.run(main())