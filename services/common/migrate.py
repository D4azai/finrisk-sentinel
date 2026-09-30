import asyncio
from importlib.resources import files

import asyncpg

from services.common.settings import InfrastructureSettings


async def migrate():
    settings = InfrastructureSettings()
    connection = await asyncpg.connect(settings.database_url.get_secret_value())
    try:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(7183451)")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)"
            )
            for path in sorted(files("services.common").joinpath("migrations").iterdir(), key=str):
                if path.name.endswith(".sql"):
                    applied = await connection.fetchval(
                        "SELECT 1 FROM schema_migrations WHERE name=$1", path.name
                    )
                    if not applied:
                        await connection.execute(path.read_text(encoding="utf-8"))
                        await connection.execute(
                            "INSERT INTO schema_migrations(name) VALUES($1)", path.name
                        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(migrate())
