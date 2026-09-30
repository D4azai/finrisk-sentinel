"""Bounded synthetic end-to-end smoke/load probe; requires explicit integration mode."""

import argparse
import asyncio
import json
import os
import time
from uuid import uuid4

from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from services.common.broker import dispatch_once, make_producer
from services.common.contracts import RawEnvelope, utcnow
from services.common.runtime import run
from services.common.settings import InfrastructureSettings
from services.common.store import Record, Store
from services.ingestion.config.settings import IngestionSettings
from services.ingestion.processor import process_record


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=1000)
    args = parser.parse_args()
    if os.getenv("FINRISK_RUN_INTEGRATION") != "1" or not 1 <= args.events <= 10000:
        raise ValueError("Run on a test stack with FINRISK_RUN_INTEGRATION=1 and 1..10000 events")
    settings = InfrastructureSettings()
    if settings.environment == "production":
        raise ValueError("Load probe cannot run in production")
    topic = "test.load." + uuid4().hex
    symbol = "TEST" + uuid4().hex[:12].upper()
    store = await Store.open(settings)
    producer = make_producer(settings)
    admin = AIOKafkaAdminClient(**settings.kafka_options())
    consumer = AIOKafkaConsumer(
        topic,
        **settings.kafka_options(),
        group_id=None,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await admin.start()
    await admin.create_topics([NewTopic(topic, 1, 1)])
    await producer.start()
    await consumer.start()
    started = time.perf_counter()
    try:
        for index in range(args.events):
            ms = int(utcnow().timestamp() * 1000)
            envelope = RawEnvelope(
                payload_text=json.dumps(
                    {
                        "s": symbol,
                        "t": index,
                        "p": "100.001",
                        "q": "0.01",
                        "T": ms,
                        "E": ms,
                    }
                )
            )
            await producer.send_and_wait(
                topic, envelope.model_dump_json().encode(), key=symbol.encode()
            )
        config = IngestionSettings(_env_file=None, max_allowed_staleness_sec=3600)
        for _ in range(args.events):
            async with asyncio.timeout(30):
                message = await consumer.getone()
            outcome = await process_record(
                store, Record(topic, message.partition, message.offset, message.value), config
            )
            if outcome != "accepted":
                raise RuntimeError("Unexpected probe outcome")
        while await dispatch_once(store, producer, settings.clean_topic):
            pass
        elapsed = time.perf_counter() - started
        print(
            json.dumps(
                {
                    "events": args.events,
                    "seconds": round(elapsed, 3),
                    "events_per_second": round(args.events / elapsed, 1),
                    "scope": "single sequential producer/worker; not a capacity certification",
                }
            )
        )
    finally:
        await consumer.stop()
        await producer.stop()
        await admin.delete_topics([topic])
        await admin.close()
        await store.close()


if __name__ == "__main__":
    run(main)
