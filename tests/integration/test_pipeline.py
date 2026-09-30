import asyncio
import json
import os
from datetime import timedelta
from importlib.resources import files
from uuid import uuid4

import asyncpg
import pytest
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from services.common.broker import dispatch_once, make_producer
from services.common.contracts import RawEnvelope, utcnow
from services.common.settings import InfrastructureSettings
from services.common.store import Backpressure, Record, Store
from services.ingestion.config.settings import IngestionSettings
from services.ingestion.processor import process_record

pytestmark = pytest.mark.integration


@pytest.fixture
async def store():
    if os.environ.get("FINRISK_RUN_INTEGRATION") != "1":
        pytest.skip("Set FINRISK_RUN_INTEGRATION=1 with a dedicated PostgreSQL/Kafka test stack")
    config = InfrastructureSettings()
    # Isolate every test in its own schema; never truncate application tables.
    schema = "test_" + uuid4().hex
    admin = await asyncpg.connect(config.database_url.get_secret_value())
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    await admin.close()
    pool = await asyncpg.create_pool(
        config.database_url.get_secret_value(),
        min_size=1,
        max_size=5,
        server_settings={"search_path": schema},
    )
    async with pool.acquire() as connection:
        await connection.execute(
            files("services.common")
            .joinpath("migrations/001_pipeline.sql")
            .read_text(encoding="utf-8")
        )
    result = Store(pool, config)
    try:
        yield result
    finally:
        await pool.close()
        admin = await asyncpg.connect(config.database_url.get_secret_value())
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


def record(sequence=1, offset=0, *, stamp=None, received=None, **changes):
    stamp = stamp or utcnow()
    ms = int(stamp.timestamp() * 1000)
    payload = {
        "e": "trade",
        "s": "BTCUSDT",
        "p": "100.00000001",
        "q": "0.1",
        "t": sequence,
        "T": ms,
        "E": ms,
        **changes,
    }
    envelope = RawEnvelope(payload_text=json.dumps(payload), received_at=received or utcnow())
    return Record("test.raw", 0, offset, envelope.model_dump_json().encode())


async def scalar(store, query, *args):
    async with store.pool.acquire() as connection:
        return await connection.fetchval(query, *args)


async def test_duplicate_and_restart_do_not_repeat_side_effects(store):
    value = record()
    config = IngestionSettings(_env_file=None)
    assert await process_record(store, value, config) == "accepted"
    restarted = Store(store.pool, store.settings)
    assert await process_record(restarted, value, config) == "redelivered"
    assert (
        await process_record(restarted, Record(value.topic, 0, 1, value.value), config)
        == "duplicate"
    )
    assert await scalar(store, "SELECT count(*) FROM trades") == 1
    assert await scalar(store, "SELECT count(*) FROM outbox") == 1
    assert await scalar(store, "SELECT offset_id FROM partition_checkpoints") == 1


async def test_bad_high_id_cannot_poison_sequence(store):
    config = IngestionSettings(_env_file=None)
    assert await process_record(store, record(1000, p="NaN"), config) == "quarantined"
    assert await scalar(store, "SELECT count(*) FROM instrument_state") == 0
    assert await process_record(store, record(1, 1), config) == "accepted"
    assert await scalar(store, "SELECT last_sequence FROM instrument_state") == 1


async def test_transaction_rolls_back_result_and_checkpoint_on_outbox_failure(store, monkeypatch):
    async def fail(*args):
        raise RuntimeError("injected outbox failure")

    original = store.enqueue
    monkeypatch.setattr(store, "enqueue", fail)
    config = IngestionSettings(_env_file=None)
    value = record()
    with pytest.raises(RuntimeError):
        await process_record(store, value, config)
    for table in ("inbox", "trades", "instrument_state", "partition_checkpoints"):
        assert await scalar(store, f"SELECT count(*) FROM {table}") == 0
    monkeypatch.setattr(store, "enqueue", original)
    assert await process_record(store, value, config) == "accepted"


async def test_late_history_does_not_replace_live_price(store):
    config = IngestionSettings(_env_file=None)
    await process_record(store, record(5), config)
    past = utcnow() - timedelta(days=1)
    fresh = []
    await process_record(
        store, record(4, 1, stamp=past, received=past), config, on_fresh=lambda: fresh.append(True)
    )
    assert not fresh
    assert await scalar(store, "SELECT count(*) FROM trades") == 2
    assert await scalar(store, "SELECT sequence_id FROM latest_trades") == 5
    assert await scalar(store, "SELECT last_sequence FROM instrument_state") == 5


async def test_gap_and_conflicting_trade_are_durable(store):
    config = IngestionSettings(_env_file=None)
    first = record(1)
    await process_record(store, first, config)
    await process_record(store, record(3, 1), config)
    assert await scalar(store, "SELECT count(*) FROM quality_events") == 1
    conflicting = json.loads(first.value)
    payload = json.loads(conflicting["payload_text"])
    payload["p"] = "99"
    conflicting["payload_text"] = json.dumps(payload)
    assert (
        await process_record(
            store, Record("test.raw", 0, 2, json.dumps(conflicting).encode()), config
        )
        == "quarantined"
    )
    assert await scalar(store, "SELECT reason FROM quarantine") == "conflicting_trade_id"
    assert await scalar(store, "SELECT count(*) FROM trades") == 2


async def test_concurrent_duplicate_delivery(store):
    value = record()
    config = IngestionSettings(_env_file=None)
    outcomes = await asyncio.gather(*(process_record(store, value, config) for _ in range(5)))
    assert outcomes.count("accepted") == 1
    assert await scalar(store, "SELECT count(*) FROM trades") == 1


async def test_bad_json_and_tombstone_are_quarantined(store):
    config = IngestionSettings(_env_file=None)
    for offset, value in enumerate((b"{", None, b"[]")):
        assert (
            await process_record(store, Record("test.raw", 0, offset, value), config)
            == "quarantined"
        )
    assert await scalar(store, "SELECT count(*) FROM quarantine") == 3


async def test_null_character_is_archived_then_quarantined(store):
    envelope = RawEnvelope(payload_text="\x00")
    async with store.pool.acquire() as connection:
        await store.archive_raw(connection, envelope, "invalid")
    assert await scalar(store, "SELECT count(*) FROM raw_frames") == 1
    value = Record("test.raw", 0, 0, envelope.model_dump_json().encode())
    assert await process_record(store, value, IngestionSettings(_env_file=None)) == "quarantined"


async def test_collector_ownership_prevents_duplicate_shards(store):
    instrument = "test:" + uuid4().hex
    async with store.collector_ownership([instrument]):
        with pytest.raises(RuntimeError, match="already owns"):
            async with store.collector_ownership([instrument]):
                pass
    async with store.collector_ownership([instrument]):
        pass


async def test_broker_failure_keeps_outbox_and_retry_marks_delivered(store):
    await process_record(store, record(), IngestionSettings(_env_file=None))

    class Producer:
        failing = True
        sent = 0

        async def send_and_wait(self, *args, **kwargs):
            if self.failing:
                raise OSError("broker offline")
            self.sent += 1

    producer = Producer()
    with pytest.raises(OSError):
        await dispatch_once(store, producer, store.settings.clean_topic)
    assert await scalar(store, "SELECT count(*) FROM outbox WHERE published_at IS NULL") == 1
    producer.failing = False
    assert await dispatch_once(store, producer, store.settings.clean_topic) == 1
    assert await dispatch_once(store, producer, store.settings.clean_topic) == 0


async def test_backpressure_does_not_ack_or_lose_current_record(store):
    store.settings.max_outbox_pending = 1
    config = IngestionSettings(_env_file=None)
    await process_record(store, record(1), config)
    with pytest.raises(Backpressure):
        await process_record(store, record(2, 1), config)
    assert await scalar(store, "SELECT offset_id FROM partition_checkpoints") == 0
    assert await scalar(store, "SELECT count(*) FROM trades") == 1


async def test_real_kafka_publish_consume_and_replay_after_missing_commit(store):
    topic = "test.finrisk." + uuid4().hex
    admin = AIOKafkaAdminClient(**store.settings.kafka_options())
    await admin.start()
    await admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
    producer = make_producer(store.settings)
    await producer.start()
    group = "test-" + uuid4().hex

    def consumer():
        return AIOKafkaConsumer(
            topic,
            **store.settings.kafka_options(),
            group_id=group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )

    first = consumer()
    second = None
    try:
        value = record()
        await producer.send_and_wait(topic, value.value, key=b"binance:spot:BTCUSDT")
        await first.start()
        async with asyncio.timeout(30):
            message = await first.getone()
        source = Record(topic, message.partition, message.offset, message.value)
        config = IngestionSettings(_env_file=None)
        assert await process_record(store, source, config) == "accepted"
        await first.stop()  # Simulates DB committed, Kafka commit never happened.
        second = consumer()
        await second.start()
        async with asyncio.timeout(30):
            repeated = await second.getone()
        assert repeated.offset == message.offset
        assert (
            await process_record(
                store, Record(topic, repeated.partition, repeated.offset, repeated.value), config
            )
            == "redelivered"
        )
        await second.commit({TopicPartition(topic, repeated.partition): repeated.offset + 1})
        assert await scalar(store, "SELECT count(*) FROM trades") == 1
    finally:
        await first.stop()
        if second:
            await second.stop()
        await producer.stop()
        await admin.delete_topics([topic])
        await admin.close()
