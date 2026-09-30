"""Ingest a reviewed normalized JSON export from a market-data provider."""

import argparse
import asyncio
from pathlib import Path

import asyncpg

from services.analytics.market import MarketImport, import_market
from services.common.settings import InfrastructureSettings


async def run(args):
    with args.file.open("rb") as handle:
        raw = handle.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("File exceeds 8 MiB")
    batch = MarketImport.model_validate_json(raw)
    if args.validate_only:
        print(
            f"Valid export: {len(batch.bars)} bars, {len(batch.sessions)} sessions, {len(batch.fx)} FX rates"
        )
        return
    settings = InfrastructureSettings()
    connection = await asyncpg.connect(settings.database_url.get_secret_value())
    try:
        print(
            await import_market(
                connection, raw, environment=settings.environment, allow_demo=args.allow_demo
            )
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--allow-demo", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    asyncio.run(run(parser.parse_args()))
