from contextlib import asynccontextmanager
from uuid import uuid4

import asyncpg
from fastapi import HTTPException


async def verify_runtime_role(connection):
    privileged = await connection.fetchval(
        """SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"""
    )
    owns_table = await connection.fetchval(
        """SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='saas' AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user))"""
    )
    dangerous_membership = await connection.fetchval(
        """SELECT EXISTS(SELECT 1 FROM pg_roles r WHERE
           pg_has_role(current_user,r.oid,'MEMBER') AND
           (r.rolsuper OR r.rolbypassrls OR EXISTS(
               SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='saas' AND c.relowner=r.oid)))"""
    )
    if privileged or owns_table or dangerous_membership:
        raise RuntimeError("API database role must not own tables or bypass row security")


async def open_pool(settings):
    pool = await asyncpg.create_pool(
        settings.database_url.get_secret_value(),
        min_size=1,
        max_size=settings.pool_size,
        command_timeout=10,
        timeout=5,
        server_settings={"application_name": "finrisk-api"},
    )
    try:
        async with pool.acquire() as connection:
            await verify_runtime_role(connection)
            await connection.fetchval("SELECT 1 FROM saas.users LIMIT 1")
            await connection.fetchval("SELECT 1 FROM saas.portfolio_transactions LIMIT 1")
            await connection.fetchval("SELECT 1 FROM saas.instruments LIMIT 1")
            await connection.fetchval("SELECT 1 FROM saas.price_bars LIMIT 1")
            await connection.fetchval("SELECT 1 FROM saas.paper_accounts LIMIT 1")
    except BaseException:
        await pool.close()
        raise
    return pool


@asynccontextmanager
async def transaction(
    pool, identity, tenant_id=None, *, allow_demo_market_data=False, isolation="read_committed"
):
    async with pool.acquire(timeout=5) as connection, connection.transaction(isolation=isolation):
        # Local settings disappear on COMMIT/ROLLBACK, including pooled connections.
        await connection.execute(
            """SELECT set_config('app.issuer',$1,true),set_config('app.subject',$2,true),
               set_config('app.user_id','',true),set_config('app.tenant_id',$3,true),
               set_config('app.allow_demo_market_data',$4,true)""",
            identity.issuer,
            identity.subject,
            str(tenant_id) if tenant_id else "",
            "true" if allow_demo_market_data else "false",
        )
        user = await connection.fetchrow(
            "SELECT id,active FROM saas.users WHERE issuer=$1 AND subject=$2",
            identity.issuer,
            identity.subject,
        )
        if user is None:
            await connection.execute(
                """INSERT INTO saas.users(id,issuer,subject) VALUES($1,$2,$3)
                   ON CONFLICT(issuer,subject) DO NOTHING""",
                uuid4(),
                identity.issuer,
                identity.subject,
            )
            user = await connection.fetchrow(
                "SELECT id,active FROM saas.users WHERE issuer=$1 AND subject=$2",
                identity.issuer,
                identity.subject,
            )
        if not user["active"]:
            raise HTTPException(403, "Account disabled")
        await connection.execute("SELECT set_config('app.user_id',$1,true)", str(user["id"]))
        role = None
        if tenant_id:
            role = await connection.fetchval(
                "SELECT role FROM saas.memberships WHERE tenant_id=$1 AND user_id=$2",
                tenant_id,
                user["id"],
            )
            if role is None:
                raise HTTPException(404, "Workspace not found")
        yield connection, user["id"], role


async def audit(connection, tenant, user, action, resource):
    await connection.execute(
        """INSERT INTO saas.audit_events(id,tenant_id,actor_id,action,resource_id)
           VALUES($1,$2,$3,$4,$5)""",
        uuid4(),
        tenant,
        user,
        action,
        resource,
    )
