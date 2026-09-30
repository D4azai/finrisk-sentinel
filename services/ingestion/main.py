import asyncio
from contextlib import AsyncExitStack

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.errors import CommitFailedError

from services.common.broker import dispatch_forever, make_producer
from services.common.runtime import Health, bounded_close, run, supervise
from services.common.settings import InfrastructureSettings
from services.common.store import Backpressure, Record, Store
from services.ingestion.config.settings import IngestionSettings
from services.ingestion.processor import process_record


async def consume(consumer, store, config, health):
    async for message in consumer:
        record = Record(message.topic, message.partition, message.offset, message.value)
        while True:
            try:
                outcome = await process_record(store, record, config, on_fresh=health.touch)
                break
            except Backpressure:
                health.last_frame = 0
                await asyncio.sleep(1)
        health.processed.labels(outcome).inc()
        try:
            # Commit only the completed record, never the consumer's prefetched position.
            await consumer.commit(
                {TopicPartition(message.topic, message.partition): message.offset + 1}
            )
        except CommitFailedError:
            # Reassignment can repeat the record. The database inbox deduplicates it.
            health.failures.labels("rebalance_commit").inc()


async def main():
    infrastructure, config = InfrastructureSettings(), IngestionSettings()
    health = Health(infrastructure)
    async with AsyncExitStack() as stack:
        store = await Store.open(infrastructure)
        stack.push_async_callback(bounded_close, store.close)
        producer = make_producer(infrastructure)
        stack.push_async_callback(bounded_close, producer.stop)
        await producer.start()
        consumer = AIOKafkaConsumer(
            infrastructure.raw_topic,
            **infrastructure.kafka_options(),
            group_id=config.consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            isolation_level="read_committed",
            max_poll_records=1,
            max_poll_interval_ms=120000,
            fetch_max_bytes=1048576,
            max_partition_fetch_bytes=1048576,
        )
        stack.push_async_callback(bounded_close, consumer.stop)
        await consumer.start()
        stack.push_async_callback(health.close)
        await health.start()
        await supervise(
            consume(consumer, store, config, health),
            dispatch_forever(
                store,
                producer,
                [
                    infrastructure.clean_topic,
                    infrastructure.quality_topic,
                    infrastructure.quarantine_topic,
                ],
                health,
            ),
            health.watch(store),
        )


if __name__ == "__main__":
    run(main)
