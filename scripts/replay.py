"""Republish archived raw frames within an explicit time range.

Uses a new delivery ID; canonical event IDs still deduplicate. This is a repair
tool for retained inputs, not a way to invent trades absent from the archive.
"""

import argparse
import json
from datetime import datetime
from uuid import uuid4

from services.common.contracts import RawEnvelope
from services.common.runtime import run
from services.common.settings import InfrastructureSettings
from services.common.store import Store
from services.market_data.main import routing_key


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-time", required=True, type=datetime.fromisoformat)
    parser.add_argument("--to-time", required=True, type=datetime.fromisoformat)
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()
    if (
        not args.from_time.tzinfo
        or not args.to_time.tzinfo
        or args.to_time <= args.from_time
        or not 1 <= args.limit <= 10000
    ):
        raise ValueError("Use an increasing UTC time interval and a limit between 1 and 10000")
    store = await Store.open(InfrastructureSettings())
    try:
        async with store.pool.acquire() as connection, connection.transaction():
            rows = await connection.fetch(
                """SELECT envelope FROM raw_frames WHERE received_at >= $1 AND received_at < $2
                   ORDER BY received_at,event_id LIMIT $3""",
                args.from_time,
                args.to_time,
                args.limit + 1,
            )
            if len(rows) > args.limit:
                raise ValueError(
                    "Interval exceeds replay limit; select smaller non-overlapping windows"
                )
            pending = await connection.fetchval(
                "SELECT count(*) FROM outbox WHERE published_at IS NULL"
            )
            if pending + len(rows) > store.settings.max_outbox_pending:
                raise ValueError("Replay would exceed outbox budget; drain first")
            replay_id = str(uuid4())
            for row in rows:
                envelope = RawEnvelope.model_validate(json.loads(row["envelope"]))
                await store.enqueue(
                    connection,
                    replay_id + ":" + str(envelope.event_id),
                    store.settings.raw_topic,
                    routing_key(envelope),
                    envelope.model_dump_json().encode(),
                )
        print(f"Queued {len(rows)} archived frames for replay.")
    finally:
        await store.close()


if __name__ == "__main__":
    run(main)
