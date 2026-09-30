"""Inspect canonical Kafka records; run inside the private Compose network."""

import asyncio
import json

from aiokafka import AIOKafkaConsumer

from services.common.settings import InfrastructureSettings


async def main():
    settings = InfrastructureSettings()
    consumer = AIOKafkaConsumer(
        settings.clean_topic,
        **settings.kafka_options(),
        group_id=None,
        auto_offset_reset="latest",
        enable_auto_commit=False,
        isolation_level="read_committed",
    )
    await consumer.start()
    try:
        async for message in consumer:
            trade = json.loads(message.value)
            print(
                f"{trade['instrument_id']} price={trade['price']} volume={trade['volume']} "
                f"sequence={trade['sequence_id']} quality={trade['quality_flags']}",
                flush=True,
            )
    finally:
        await consumer.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
