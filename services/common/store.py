import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal

import asyncpg

from services.common.contracts import utcnow


def lock_key(value):
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)


@dataclass(frozen=True)
class Record:
    topic: str
    partition: int
    offset: int
    value: bytes


class Backpressure(Exception):
    pass


class Store:
    def __init__(self, pool, settings):
        self.pool = pool
        self.settings = settings

    @classmethod
    async def open(cls, settings):
        pool = await asyncpg.create_pool(
            settings.database_url.get_secret_value(),
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        return cls(pool, settings)

    async def close(self):
        await self.pool.close()

    @asynccontextmanager
    async def collector_ownership(self, instruments):
        # The SAME session holds ownership and writes received frames. A lost
        # connection cannot keep writing under an expired/reassigned lease.
        connection = await asyncpg.connect(
            self.settings.database_url.get_secret_value(), command_timeout=30
        )
        try:
            for instrument in sorted(instruments):
                owned = await connection.fetchval(
                    "SELECT pg_try_advisory_lock($1)", lock_key("collector:" + instrument)
                )
                if not owned:
                    raise RuntimeError("A collector already owns a requested instrument")
            yield connection
        finally:
            await connection.close()

    async def enqueue(self, connection, event_id, topic, key, payload):
        await connection.execute(
            """INSERT INTO outbox(event_id,topic,message_key,payload) VALUES($1,$2,$3,$4)
               ON CONFLICT(topic,event_id) DO NOTHING""",
            event_id,
            topic,
            key,
            payload,
        )

    async def archive_raw(self, connection, envelope, key):
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock($1)", lock_key("raw-capacity"))
            pending = await connection.fetchval(
                "SELECT count(*) FROM outbox WHERE published_at IS NULL AND topic=$1",
                self.settings.raw_topic,
            )
            if pending >= self.settings.max_outbox_pending:
                raise Backpressure("Raw outbox is full")
            await connection.execute(
                """INSERT INTO raw_frames(event_id,received_at,envelope) VALUES($1,$2,$3)
                   ON CONFLICT DO NOTHING""",
                envelope.event_id,
                envelope.received_at,
                envelope.model_dump_json(),
            )
            await self.enqueue(
                connection,
                str(envelope.event_id),
                self.settings.raw_topic,
                key,
                envelope.model_dump_json().encode(),
            )

    async def quality(self, connection, event_id, details):
        payload = json.dumps({"schema_version": 1, "event_id": event_id, **details})
        await connection.execute(
            "INSERT INTO quality_events(event_id,details) VALUES($1,$2) ON CONFLICT DO NOTHING",
            event_id,
            payload,
        )
        await self.enqueue(
            connection,
            event_id,
            self.settings.quality_topic,
            details.get("instrument_id", "feed"),
            payload.encode(),
        )

    async def feed_interruption(self, connection, event_id, instruments, reason):
        async with connection.transaction():
            await self.quality(
                connection,
                event_id,
                {
                    "reason": reason,
                    "instruments": instruments,
                    "observed_at": utcnow().isoformat(),
                    "recovery_status": "unverified",
                },
            )

    async def _quarantine(self, connection, event_id, reason, payload):
        await connection.execute(
            """INSERT INTO quarantine(event_id,reason,payload) VALUES($1,$2,$3)
               ON CONFLICT DO NOTHING""",
            event_id,
            reason,
            payload,
        )
        # Original bytes live in the database; events carry a bounded reference.
        await self.enqueue(
            connection,
            event_id,
            self.settings.quarantine_topic,
            "invalid",
            json.dumps({"schema_version": 1, "event_id": event_id, "reason": reason}).encode(),
        )

    async def process(self, record, trade=None, rejection=None):
        """Atomically archive input, save result, update state and enqueue output.
        Kafka commits happen afterwards; duplicate delivery is harmless."""
        event_ref = f"{record.topic}:{record.partition}:{record.offset}"
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock($1)", lock_key("clean-capacity"))
            pending = await connection.fetchval(
                "SELECT count(*) FROM outbox WHERE published_at IS NULL AND topic<>$1",
                self.settings.raw_topic,
            )
            if pending >= self.settings.max_outbox_pending:
                raise Backpressure("Ingestion outbox is full")
            await connection.execute(
                "SELECT pg_advisory_xact_lock($1)",
                lock_key(f"partition:{record.topic}:{record.partition}"),
            )
            inserted = await connection.fetchval(
                """INSERT INTO inbox(topic,partition_id,offset_id,payload) VALUES($1,$2,$3,$4)
                   ON CONFLICT DO NOTHING RETURNING 1""",
                record.topic,
                record.partition,
                record.offset,
                record.value or b"",
            )
            if not inserted:
                return "redelivered"
            outcome = "quarantined"
            if rejection:
                await self._quarantine(connection, event_ref, rejection, record.value or b"")
            else:
                outcome = await self._trade(connection, trade, event_ref, record.value)
            await connection.execute(
                """INSERT INTO partition_checkpoints VALUES($1,$2,$3)
                   ON CONFLICT(topic,partition_id) DO UPDATE SET
                   offset_id=GREATEST(partition_checkpoints.offset_id,EXCLUDED.offset_id)""",
                record.topic,
                record.partition,
                record.offset,
            )
            return outcome

    async def _trade(self, connection, trade, event_ref, raw):
        await connection.execute(
            "SELECT pg_advisory_xact_lock($1)", lock_key("instrument:" + trade.instrument_id)
        )
        existing = await connection.fetchval(
            "SELECT trade FROM trades WHERE event_id=$1", trade.event_id
        )
        if existing:
            previous = json.loads(existing)
            fields = ("instrument_id", "sequence_id", "timestamp")
            current = trade.model_dump(mode="json")
            conflict = any(previous[field] != current[field] for field in fields)
            conflict |= any(
                Decimal(previous[f]) != Decimal(current[f]) for f in ("price", "volume")
            )
            if conflict:
                await self._quarantine(connection, event_ref, "conflicting_trade_id", raw)
                return "quarantined"
            return "duplicate"
        last = await connection.fetchval(
            "SELECT last_sequence FROM instrument_state WHERE instrument_id=$1",
            trade.instrument_id,
        )
        flags = list(trade.quality_flags)
        if last is not None and trade.sequence_id > last + 1:
            flags.append("sequence_gap")
            await self.quality(
                connection,
                trade.event_id + ":gap",
                {
                    "instrument_id": trade.instrument_id,
                    "reason": "sequence_gap",
                    "missing_from": last + 1,
                    "missing_to": trade.sequence_id - 1,
                    "recovery_status": "unverified",
                },
            )
        if last is not None and trade.sequence_id < last:
            flags.append("out_of_order")
        trade = trade.model_copy(update={"quality_flags": tuple(flags)})
        await connection.execute(
            "INSERT INTO trades VALUES($1,$2,$3,$4,$5)",
            trade.event_id,
            trade.instrument_id,
            trade.sequence_id,
            trade.timestamp,
            trade.model_dump_json(),
        )
        await connection.execute(
            """INSERT INTO instrument_state VALUES($1,$2)
               ON CONFLICT(instrument_id) DO UPDATE SET
               last_sequence=GREATEST(instrument_state.last_sequence,EXCLUDED.last_sequence)""",
            trade.instrument_id,
            trade.sequence_id,
        )
        if "late" not in flags:
            await connection.execute(
                """INSERT INTO latest_trades VALUES($1,$2,$3,$4)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                   sequence_id=EXCLUDED.sequence_id,event_at=EXCLUDED.event_at,trade=EXCLUDED.trade
                   WHERE EXCLUDED.sequence_id > latest_trades.sequence_id
                   AND EXCLUDED.event_at >= latest_trades.event_at""",
                trade.instrument_id,
                trade.sequence_id,
                trade.timestamp,
                trade.model_dump_json(),
            )
        await self.enqueue(
            connection,
            trade.event_id,
            self.settings.clean_topic,
            trade.instrument_id,
            trade.model_dump_json().encode(),
        )
        return "accepted"
