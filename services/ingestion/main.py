import asyncio
import logging
import signal
from services.ingestion.config.settings import settings
from services.ingestion.consumer.stream_consumer import ZMQStreamConsumer
from services.ingestion.filters.sequence_check import SequenceValidationFilter
from services.ingestion.filters.health_check import HealthCheckFilter
from services.ingestion.normalizers.binance_adapter import BinanceAdapter
from services.ingestion.pipeline.processing_chain import IngestionPipeline
from services.ingestion.publisher.clean_publisher import CleanStreamPublisher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ingestion.main")


async def shutdown(loop: asyncio.AbstractEventLoop, consumer: ZMQStreamConsumer, publisher: CleanStreamPublisher):
    logger.info("Shutting down Ingestion Service...")
    consumer.close()
    publisher.close()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


async def main():
    loop = asyncio.get_running_loop()
    consumer = ZMQStreamConsumer(
        endpoint=settings.zmq_sub_endpoint,
        subscriptions=settings.subscriptions,
        server_public_key=settings.market_data_public_key
    )
    publisher = CleanStreamPublisher(settings.zmq_clean_pub_endpoint)

    consumer.start()
    publisher.start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(loop, consumer, publisher)))

    pipeline = IngestionPipeline([
        SequenceValidationFilter(),
        HealthCheckFilter(max_staleness_sec=settings.max_allowed_staleness_sec)
    ])
    adapter = BinanceAdapter()

    logger.info("Ingestion Service listening for incoming streams...")

    async for topic, raw_msg in consumer.listen():
        filtered_msg = await pipeline.execute(raw_msg)
        if filtered_msg:
            canonical_trade = adapter.adapt(filtered_msg)
            await publisher.publish(canonical_trade)
            logger.info(f"[INGESTED & PUBLISHED]: {canonical_trade.symbol} @ {canonical_trade.price}")


if __name__ == "__main__":
    asyncio.run(main())