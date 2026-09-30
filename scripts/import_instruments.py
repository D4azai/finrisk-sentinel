"""Import reviewed reference data with the migration/operator database credential."""

import argparse
import asyncio
from pathlib import Path

import asyncpg

from services.common.settings import InfrastructureSettings
from services.instruments.catalog import MAX_CATALOG_BYTES, import_catalog, parse_catalog


async def run(args):
    with args.file.open("rb") as handle:
        raw = handle.read(MAX_CATALOG_BYTES + 1)
    catalog = parse_catalog(raw)
    if args.validate_only:
        print(f"Valid catalog: {len(catalog.instruments)} records; no database changes.")
        return
    settings = InfrastructureSettings()
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=5)
    try:
        count = await import_catalog(
            connection,
            raw,
            environment=settings.environment,
            allow_demo=args.allow_demo,
        )
        print(f"Imported {count} catalog records atomically.")
    finally:
        await connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--allow-demo", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
