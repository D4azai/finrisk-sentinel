"""Atomic imports by a database operator, never by a tenant API credential."""

import hashlib
from uuid import uuid4

from services.instruments.models import CatalogImport

MAX_CATALOG_BYTES = 8 * 1024 * 1024


def parse_catalog(raw: bytes) -> CatalogImport:
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("Catalog file exceeds 8 MiB")
    return CatalogImport.model_validate_json(raw)


async def import_catalog(connection, raw: bytes, *, environment: str, allow_demo: bool = False):
    catalog = parse_catalog(raw)
    if environment not in {"production", "development", "test"}:
        raise ValueError("Unknown deployment environment")
    if any(item.is_demo for item in catalog.instruments) and (
        environment == "production" or not allow_demo
    ):
        raise ValueError("Demo instruments require explicit non-production enablement")
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(7183453)")
        for item in catalog.instruments:
            previous = await connection.fetchrow(
                "SELECT * FROM saas.instruments WHERE market=$1 AND symbol=$2 AND currency=$3",
                item.market,
                item.symbol,
                item.currency,
            )
            if previous:
                # Symbol reuse and security identity changes need a separate lifecycle workflow.
                if previous["isin"] != item.isin or previous["is_demo"] != item.is_demo:
                    raise ValueError("Cannot replace a listing's ISIN or demo classification")
                if item.verified_at < previous["verified_at"]:
                    raise ValueError("Cannot overwrite newer reference data")
                await connection.execute(
                    """UPDATE saas.instruments SET name=$2,active=$3,source=$4,
                       verified_at=$5,updated_at=now() WHERE id=$1""",
                    previous["id"],
                    item.name,
                    item.active,
                    item.source,
                    item.verified_at,
                )
            else:
                await connection.execute(
                    """INSERT INTO saas.instruments
                       (id,market,symbol,currency,name,isin,is_demo,active,source,verified_at)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                    uuid4(),
                    item.market,
                    item.symbol,
                    item.currency,
                    item.name,
                    item.isin,
                    item.is_demo,
                    item.active,
                    item.source,
                    item.verified_at,
                )
        await connection.execute(
            "INSERT INTO saas.catalog_imports(id,content_sha256,record_count) VALUES($1,$2,$3)",
            uuid4(),
            hashlib.sha256(raw).hexdigest(),
            len(catalog.instruments),
        )
    return len(catalog.instruments)
