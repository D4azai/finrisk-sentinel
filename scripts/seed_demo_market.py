"""Install explicitly fictional reference data, daily history, calendars and FX."""

import asyncio

import asyncpg

from services.analytics.demo import seed_demo
from services.common.settings import InfrastructureSettings


async def main():
    settings = InfrastructureSettings()
    conn = await asyncpg.connect(settings.database_url.get_secret_value())
    try:
        print(await seed_demo(conn, environment=settings.environment))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
