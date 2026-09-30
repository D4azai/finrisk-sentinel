import asyncio
import logging

from aiokafka import AIOKafkaProducer

from services.common.store import lock_key

logger = logging.getLogger(__name__)


def make_producer(settings):
    return AIOKafkaProducer(
        **settings.kafka_options(),
        enable_idempotence=True,
        acks="all",
        max_request_size=1048576,
        request_timeout_ms=15000,
    )


async def dispatch_once(store, producer, topic, metrics=None):
    # One ordered dispatcher per topic, coordinated across service replicas.
    # At-least-once: a crash after publish but before marking can repeat an event.
    async with store.pool.acquire() as connection, connection.transaction():
        locked = await connection.fetchval(
            "SELECT pg_try_advisory_xact_lock($1)", lock_key("outbox:" + topic)
        )
        if not locked:
            return 0
        rows = await connection.fetch(
            """SELECT id,message_key,payload FROM outbox WHERE topic=$1
               AND published_at IS NULL ORDER BY id LIMIT 25 FOR UPDATE""",
            topic,
        )
        for row in rows:
            async with asyncio.timeout(store.settings.publish_timeout_sec):
                await producer.send_and_wait(topic, row["payload"], key=row["message_key"].encode())
            await connection.execute("UPDATE outbox SET published_at=now() WHERE id=$1", row["id"])
        if metrics:
            metrics.published.inc(len(rows))
        return len(rows)


async def dispatch_forever(store, producer, topics, health):
    while True:
        try:
            count = 0
            for topic in topics:
                count += await dispatch_once(store, producer, topic, health)
            if not count:
                # Probe even while idle; a quiet outbox is not proof of Kafka health.
                async with asyncio.timeout(store.settings.publish_timeout_sec):
                    if not await producer.client.force_metadata_update():
                        raise TimeoutError("Broker metadata unavailable")
                await asyncio.sleep(1)
            health.broker_ok = True
        except (TimeoutError, OSError) as exc:
            health.broker_ok = False
            health.failures.labels(type(exc).__name__).inc()
            logger.warning("Outbox delivery retry", extra={"error_type": type(exc).__name__})
            await asyncio.sleep(1)
        except Exception as exc:
            from aiokafka.errors import KafkaError

            if not isinstance(exc, KafkaError):
                raise
            health.broker_ok = False
            health.failures.labels("KafkaError").inc()
            logger.warning("Kafka unavailable; retained outbox will retry")
            await asyncio.sleep(1)
