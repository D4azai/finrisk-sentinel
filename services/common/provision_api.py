"""Provision the local login; production roles are provisioned by deployment tooling."""

import os

import asyncpg

from services.common.settings import InfrastructureSettings


async def provision_local_api():
    settings = InfrastructureSettings()
    if settings.environment != "development":
        return
    password = os.environ.get("API_DATABASE_PASSWORD")
    if not password or len(password) < 32:
        raise ValueError("Generate a local API password with scripts/init_api_env.py")
    connection = await asyncpg.connect(settings.database_url.get_secret_value())
    try:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(7183452)")
            exists = await connection.fetchval(
                "SELECT 1 FROM pg_roles WHERE rolname='finrisk_api_login'"
            )
            if not exists:
                await connection.execute(
                    "CREATE ROLE finrisk_api_login LOGIN INHERIT NOSUPERUSER NOBYPASSRLS"
                )
            statement = await connection.fetchval(
                "SELECT format('ALTER ROLE finrisk_api_login PASSWORD %L',$1::text)", password
            )
            await connection.execute(statement)
            await connection.execute("GRANT finrisk_api TO finrisk_api_login")
    finally:
        await connection.close()
