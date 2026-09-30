import asyncio
import json
import os
import time
from importlib.resources import files
from uuid import UUID, uuid4

import asyncpg
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from services.analytics.demo import seed_demo
from services.analytics.market import import_market
from services.api.auth import Identity, TokenVerifier
from services.api.database import open_pool, transaction, verify_runtime_role
from services.api.main import create_app
from services.api.settings import APISettings
from services.common.settings import InfrastructureSettings
from services.instruments.catalog import import_catalog

pytestmark = pytest.mark.integration


@pytest.fixture
async def tenant_app():
    if os.getenv("FINRISK_RUN_INTEGRATION") != "1":
        pytest.skip("Requires the dedicated PostgreSQL integration stack")
    infra = InfrastructureSettings()
    admin_url = infra.database_url.get_secret_value()
    database = "tenant_test_" + uuid4().hex
    control = await asyncpg.connect(admin_url)
    await control.execute(f'CREATE DATABASE "{database}"')
    admin = await asyncpg.connect(admin_url, database=database)
    pool = None
    try:
        migration = files("services.common").joinpath("migrations/003_tenancy.sql").read_text()
        await admin.execute(migration)
        await admin.execute(
            files("services.common")
            .joinpath("migrations/004_portfolio_transactions.sql")
            .read_text()
        )
        await admin.execute(
            files("services.common").joinpath("migrations/005_instrument_catalog.sql").read_text()
        )
        await admin.execute(
            files("services.common").joinpath("migrations/006_market_analytics.sql").read_text()
        )
        await admin.execute(
            files("services.common").joinpath("migrations/007_paper_trading.sql").read_text()
        )
        # Synthetic reference records are confined to this disposable test database.
        for market, currency in [("XCAS", "MAD"), ("XNYS", "USD")]:
            await admin.execute(
                """INSERT INTO saas.instruments(id,market,symbol,currency,name,isin,source,verified_at)
                   VALUES($1,$2,'TEST',$3,'Test equity','US0378331005','test fixture','2026-01-01')""",
                uuid4(),
                market,
                currency,
            )
        pool = await asyncpg.create_pool(
            os.environ["API_DATABASE_URL"], database=database, min_size=1, max_size=4
        )
        async with pool.acquire() as connection:
            await verify_runtime_role(connection)
        config = APISettings(
            _env_file=None,
            _env_prefix="UNIT_API_",
            environment="test",
            allow_insecure_local=True,
            database_url=admin_url,
            oidc_issuer="https://tenant.example",
            oidc_jwks_url="https://tenant.example/jwks",
        )
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier = TokenVerifier(config, None)
        verifier.keys = {"test": key.public_key()}
        verifier.expires = time.monotonic() + 300

        def headers(subject):
            now = int(time.time())
            token = jwt.encode(
                {
                    "sub": subject,
                    "iss": config.oidc_issuer,
                    "aud": "finrisk-api",
                    "scope": "finrisk:access",
                    "iat": now,
                    "exp": now + 300,
                },
                key,
                algorithm="RS256",
                headers={"kid": "test"},
            )
            return {"Authorization": "Bearer " + token}

        app = create_app(config, pool=pool, verifier=verifier)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, headers, pool, admin, config
    finally:
        if pool:
            await pool.close()
        await admin.close()
        await control.execute(f'DROP DATABASE "{database}"')
        await control.close()


async def workspace(client, headers, user):
    response = await client.post(
        "/v1/workspaces", headers=headers(user), json={"name": user + " workspace"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def portfolio(client, headers, user, tenant):
    response = await client.post(
        f"/v1/workspaces/{tenant}/portfolios",
        headers=headers(user),
        json={"name": "Main portfolio", "base_currency": "USD"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_two_users_cannot_cross_read_write_or_delete(tenant_app):
    client, headers, pool, admin, config = tenant_app
    alice = await workspace(client, headers, "alice")
    bob = await workspace(client, headers, "bob")
    asset = await portfolio(client, headers, "alice", alice)
    await portfolio(client, headers, "bob", bob)
    for method, path, body in [
        ("GET", f"/v1/workspaces/{alice}", None),
        ("GET", f"/v1/workspaces/{alice}/portfolios", None),
        ("GET", f"/v1/workspaces/{alice}/portfolios/{asset}", None),
        ("GET", f"/v1/workspaces/{bob}/portfolios/{asset}", None),
        ("POST", f"/v1/workspaces/{alice}/portfolios", {"name": "Intrusion"}),
        (
            "PATCH",
            f"/v1/workspaces/{alice}/portfolios/{asset}",
            {"name": "Intrusion", "version": 1},
        ),
        ("DELETE", f"/v1/workspaces/{alice}/portfolios/{asset}", None),
    ]:
        response = await client.request(
            method, path, headers=headers("bob"), **({"json": body} if body else {})
        )
        assert response.status_code == 404, response.text
    for user, tenant in [("alice", alice), ("bob", bob)]:
        result = await client.get("/v1/workspaces", headers=headers(user))
        assert [w["id"] for w in result.json()["items"]] == [tenant]
    # Missing a WHERE clause still cannot reveal another tenant's records.
    async with transaction(pool, Identity(config.oidc_issuer, "bob"), UUID(bob)) as (
        connection,
        _,
        _,
    ):
        rows = await connection.fetch("SELECT * FROM saas.portfolios")
        assert len(rows) == 1 and str(rows[0]["tenant_id"]) == bob


async def test_pool_reuse_clears_context_even_after_rollback(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    await portfolio(client, headers, "alice", tenant)
    with pytest.raises(RuntimeError):
        async with transaction(pool, Identity(config.oidc_issuer, "alice"), UUID(tenant)):
            raise RuntimeError("force rollback")
    async with pool.acquire() as connection:
        assert not await connection.fetchval("SELECT current_setting('app.user_id',true)")
        assert not await connection.fetchval("SELECT current_setting('app.tenant_id',true)")
        assert await connection.fetchval("SELECT count(*) FROM saas.portfolios") == 0
        assert await connection.fetchval("SELECT count(*) FROM saas.users") == 0


async def test_readonly_member_and_revocation(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    user = (await client.get("/v1/me", headers=headers("bob"))).json()["id"]
    await admin.execute(
        "INSERT INTO saas.memberships(tenant_id,user_id,role) VALUES($1,$2,'viewer')",
        UUID(tenant),
        UUID(user),
    )
    root = f"/v1/workspaces/{tenant}/portfolios"
    assert (await client.get(root, headers=headers("bob"))).status_code == 200
    assert (await client.post(root, headers=headers("bob"), json={"name": "no"})).status_code == 403
    assert (
        await client.patch(
            root + "/" + item, headers=headers("bob"), json={"name": "no", "version": 1}
        )
    ).status_code == 403
    assert (await client.delete(root + "/" + item, headers=headers("bob"))).status_code == 403
    await admin.execute(
        "DELETE FROM saas.memberships WHERE tenant_id=$1 AND user_id=$2", UUID(tenant), UUID(user)
    )
    assert (await client.get(root, headers=headers("bob"))).status_code == 404


async def test_conflicting_updates_and_audit_are_atomic(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    results = await asyncio.gather(
        *(
            client.patch(root, headers=headers("alice"), json={"name": name, "version": 1})
            for name in ("A", "B")
        )
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM saas.audit_events WHERE action='portfolio.updated'"
        )
        == 1
    )
    assert (await client.delete(root, headers=headers("alice"))).status_code == 204
    assert (await client.get(root, headers=headers("alice"))).status_code == 404


async def test_no_authorization_no_access_and_no_mass_assignment(tenant_app):
    client, headers, pool, admin, config = tenant_app
    assert (await client.get("/v1/me")).status_code == 401
    assert (
        await client.get("/v1/workspaces", headers={"Authorization": "Bearer forged"})
    ).status_code == 401
    assert await admin.fetchval("SELECT count(*) FROM saas.users") == 0
    tenant = await workspace(client, headers, "alice")
    response = await client.post(
        f"/v1/workspaces/{tenant}/portfolios",
        headers=headers("alice"),
        json={"name": "X", "tenant_id": str(uuid4()), "created_by": str(uuid4())},
    )
    assert response.status_code == 422
    response = await client.post("/v1/workspaces", headers=headers("alice"), content=b"x" * 17000)
    assert response.status_code == 413


async def test_database_rejects_direct_cross_tenant_insert_and_role_escalation(tenant_app):
    client, headers, pool, admin, config = tenant_app
    alice = await workspace(client, headers, "alice")
    bob = await workspace(client, headers, "bob")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with transaction(pool, Identity(config.oidc_issuer, "bob"), UUID(bob)) as (
            connection,
            user,
            _,
        ):
            await connection.execute(
                "INSERT INTO saas.portfolios(tenant_id,id,name,base_currency,created_by) VALUES($1,$2,'X','USD',$3)",
                UUID(alice),
                uuid4(),
                user,
            )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with pool.acquire() as connection:
            await connection.execute("SET ROLE finrisk_workspace_bootstrap")


async def test_disabled_user_and_privileged_runtime_are_rejected(tenant_app):
    client, headers, pool, admin, config = tenant_app
    user = (await client.get("/v1/me", headers=headers("alice"))).json()["id"]
    await admin.execute("UPDATE saas.users SET active=false WHERE id=$1", UUID(user))
    assert (await client.get("/v1/me", headers=headers("alice"))).status_code == 403
    # config deliberately contains the admin DSN, unlike the injected restricted pool.
    with pytest.raises(RuntimeError, match="must not own"):
        await open_pool(config)


def trade(**changes):
    return {
        "client_request_id": str(uuid4()),
        "market": "XCAS",
        "symbol": "TEST",
        "currency": "MAD",
        "side": "buy",
        "quantity": "10.25",
        "price": "100.10",
        "fees": "2.50",
        "executed_at": "2026-01-01T12:00:00Z",
        **changes,
    }


async def test_ledger_precision_retries_and_history_protection(tenant_app):
    from decimal import Decimal

    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    body = trade()
    first = await client.post(root + "/transactions", headers=headers("alice"), json=body)
    assert first.status_code == 201, first.text
    retry = await client.post(root + "/transactions", headers=headers("alice"), json=body)
    assert retry.status_code == 200 and retry.json() == first.json()
    conflict = await client.post(
        root + "/transactions", headers=headers("alice"), json={**body, "price": "200"}
    )
    assert conflict.status_code == 409
    sale = trade(side="sell", quantity="0.25", price="120", fees="0.10")
    assert (
        await client.post(root + "/transactions", headers=headers("alice"), json=sale)
    ).status_code == 201
    holdings = (await client.get(root + "/holdings", headers=headers("alice"))).json()["items"]
    assert len(holdings) == 1
    assert Decimal(holdings[0]["quantity"]) == Decimal("10")
    assert Decimal(holdings[0]["net_cash_flow"]) == Decimal("-998.625")
    assert Decimal(holdings[0]["fees"]) == Decimal("2.60")
    assert (await client.get(root, headers=headers("alice"))).json()["version"] == 3
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM saas.audit_events WHERE action='portfolio.transaction_recorded'"
        )
        == 2
    )
    assert (await client.delete(root, headers=headers("alice"))).status_code == 409
    for change in [
        {"side": "sell", "quantity": "11"},
        {"currency": "USD"},
        {"executed_at": "2025-01-01T00:00:00Z"},
    ]:
        result = await client.post(
            root + "/transactions", headers=headers("alice"), json=trade(**change)
        )
        assert result.status_code == 409, result.text
    page = (await client.get(root + "/transactions?limit=1", headers=headers("alice"))).json()
    other = (
        await client.get(
            root + "/transactions", params={"cursor": page["next_cursor"]}, headers=headers("alice")
        )
    ).json()
    assert len(other["items"]) == 1 and other["items"][0]["id"] != page["items"][0]["id"]


async def test_ledger_concurrent_sales_and_duplicate_requests(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    body = trade(quantity="1")
    responses = await asyncio.gather(
        *[
            client.post(root + "/transactions", headers=headers("alice"), json=body)
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 201]
    responses = await asyncio.gather(
        *[
            client.post(
                root + "/transactions",
                headers=headers("alice"),
                json=trade(side="sell", quantity="1"),
            )
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    result = (await client.get(root + "/holdings", headers=headers("alice"))).json()
    assert float(result["items"][0]["quantity"]) == 0


async def test_ledger_tenant_roles_and_database_immutability(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    bob = await workspace(client, headers, "bob")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    assert (
        await client.post(root + "/transactions", headers=headers("alice"), json=trade())
    ).status_code == 201
    for endpoint in ["transactions", "holdings"]:
        assert (await client.get(root + "/" + endpoint, headers=headers("bob"))).status_code == 404
    assert (
        await client.post(root + "/transactions", headers=headers("bob"), json=trade())
    ).status_code == 404
    async with transaction(pool, Identity(config.oidc_issuer, "bob"), UUID(bob)) as (
        conn,
        _,
        _role,
    ):
        assert await conn.fetchval("SELECT count(*) FROM saas.portfolio_transactions") == 0
    user = (await client.get("/v1/me", headers=headers("bob"))).json()["id"]
    await admin.execute(
        "INSERT INTO saas.memberships(tenant_id,user_id,role) VALUES($1,$2,'viewer')",
        UUID(tenant),
        UUID(user),
    )
    assert (await client.get(root + "/holdings", headers=headers("bob"))).status_code == 200
    assert (
        await client.post(root + "/transactions", headers=headers("bob"), json=trade())
    ).status_code == 403
    for statement in [
        "DELETE FROM saas.portfolio_transactions",
        "UPDATE saas.portfolio_transactions SET quantity=0",
    ]:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with transaction(pool, Identity(config.oidc_issuer, "alice"), UUID(tenant)) as (
                conn,
                _,
                _role,
            ):
                await conn.execute(statement)


async def test_holdings_separate_exchanges_and_paginate(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    for market, currency in [("XCAS", "MAD"), ("XNYS", "USD")]:
        response = await client.post(
            root + "/transactions",
            headers=headers("alice"),
            json=trade(market=market, currency=currency),
        )
        assert response.status_code == 201
    page = (await client.get(root + "/holdings?limit=1", headers=headers("alice"))).json()
    assert page["items"][0]["currency"] == "MAD"
    page = (
        await client.get(
            root + "/holdings", params={"cursor": page["next_cursor"]}, headers=headers("alice")
        )
    ).json()
    assert len(page["items"]) == 1 and page["items"][0]["currency"] == "USD"
    assert page["next_cursor"] is None


async def test_ledger_large_decimal_products_remain_exact(tenant_app):
    from decimal import Decimal, localcontext

    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    amount = "999999999999999999.123456789012"
    response = await client.post(
        root + "/transactions",
        headers=headers("alice"),
        json=trade(quantity=amount, price=amount, fees="0.000000000001"),
    )
    assert response.status_code == 201, response.text
    holding = (await client.get(root + "/holdings", headers=headers("alice"))).json()["items"][0]
    assert holding["quantity"] == amount
    with localcontext() as context:
        context.prec = 80
        assert Decimal(holding["net_cash_flow"]) == -(Decimal(amount) ** 2) - Decimal(
            "0.000000000001"
        )


async def test_ledger_audit_failure_rolls_back_trade_and_version(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    await admin.execute("""
        CREATE FUNCTION saas.reject_test_audit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'simulated audit failure'; END $$;
        CREATE TRIGGER reject_test_audit BEFORE INSERT ON saas.audit_events
        FOR EACH ROW EXECUTE FUNCTION saas.reject_test_audit();
    """)
    response = await client.post(root + "/transactions", headers=headers("alice"), json=trade())
    assert response.status_code == 503
    assert await admin.fetchval("SELECT count(*) FROM saas.portfolio_transactions") == 0
    assert (await client.get(root, headers=headers("alice"))).json()["version"] == 1


def catalog_bytes(**changes):
    item = dict(
        market="XCAS",
        symbol="NEW",
        currency="MAD",
        name="Imported equity",
        isin="US0378331005",
        source="integration fixture",
        verified_at="2026-01-02T00:00:00Z",
    )
    return json.dumps({"schema_version": 1, "instruments": [{**item, **changes}]}).encode()


async def test_catalog_authenticated_search_and_pagination(tenant_app):
    client, headers, pool, admin, config = tenant_app
    assert (await client.get("/v1/instruments")).status_code == 401
    first = (await client.get("/v1/instruments?limit=1", headers=headers("alice"))).json()
    second = (
        await client.get(
            "/v1/instruments", params={"cursor": first["next_cursor"]}, headers=headers("alice")
        )
    ).json()
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    result = (
        await client.get(
            "/v1/instruments",
            params={"q": "test", "market": "XCAS", "currency": "MAD"},
            headers=headers("alice"),
        )
    ).json()
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["isin"] == "US0378331005"
    assert (
        await client.get("/v1/instruments", params={"q": "%"}, headers=headers("alice"))
    ).json()["items"] == []
    assert (await client.get(f"/v1/instruments/{item['id']}", headers=headers("bob"))).json()[
        "id"
    ] == item["id"]
    assert (
        await client.get(f"/v1/instruments/{uuid4()}", headers=headers("alice"))
    ).status_code == 404
    quote = await client.get(f"/v1/instruments/{item['id']}/quote", headers=headers("alice"))
    assert quote.status_code == 200 and quote.json()["status"] == "not_configured"
    assert (
        await client.post("/v1/instruments", headers=headers("alice"), json={})
    ).status_code == 405


async def test_catalog_import_preserves_identity_and_is_atomic(tenant_app):
    client, headers, pool, admin, config = tenant_app
    raw = catalog_bytes()
    assert await import_catalog(admin, raw, environment="test") == 1
    before = await admin.fetchrow("SELECT * FROM saas.instruments WHERE symbol='NEW'")
    await import_catalog(
        admin, catalog_bytes(name="Renamed equity", active=False), environment="test"
    )
    after = await admin.fetchrow("SELECT * FROM saas.instruments WHERE symbol='NEW'")
    assert before["id"] == after["id"] and after["name"] == "Renamed equity" and not after["active"]
    assert await admin.fetchval("SELECT count(*) FROM saas.catalog_imports") == 2
    assert (await client.get("/v1/instruments?active=false", headers=headers("alice"))).json()[
        "items"
    ][0]["id"] == str(before["id"])
    contents = json.loads(catalog_bytes(symbol="ROLLBACK"))
    contents["instruments"].extend(json.loads(catalog_bytes(isin="US5949181045"))["instruments"])
    with pytest.raises(ValueError, match="Cannot replace"):
        await import_catalog(admin, json.dumps(contents).encode(), environment="test")
    assert (
        await admin.fetchval("SELECT count(*) FROM saas.instruments WHERE symbol='ROLLBACK'") == 0
    )
    assert await admin.fetchval("SELECT count(*) FROM saas.catalog_imports") == 2
    with pytest.raises(ValueError, match="newer"):
        await import_catalog(
            admin, catalog_bytes(verified_at="2025-01-01T00:00:00Z"), environment="test"
        )


async def test_catalog_is_readonly_to_application_database_role(tenant_app):
    client, headers, pool, admin, config = tenant_app
    await client.get("/v1/me", headers=headers("alice"))
    for statement in [
        "DELETE FROM saas.instruments",
        "UPDATE saas.instruments SET name='tampered'",
        "SELECT * FROM saas.catalog_imports",
    ]:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with transaction(pool, Identity(config.oidc_issuer, "alice")) as (conn, _, _role):
                await conn.execute(statement)
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM saas.instruments") == 0


async def test_trades_require_matching_catalog_and_legacy_history_survives(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    assert (
        await client.post(
            root + "/transactions", headers=headers("alice"), json=trade(symbol="UNKNOWN")
        )
    ).status_code == 409
    response = await client.post(root + "/transactions", headers=headers("alice"), json=trade())
    assert response.status_code == 201 and response.json()["instrument_id"] is not None
    holding = (await client.get(root + "/holdings", headers=headers("alice"))).json()["items"][0]
    assert holding["catalog_status"] == "registered" and holding["instrument_name"] == "Test equity"
    original_id = UUID(response.json()["id"])
    legacy_request = uuid4()
    await admin.execute(
        """INSERT INTO saas.portfolio_transactions
        (tenant_id,portfolio_id,id,client_request_id,market,symbol,currency,side,quantity,price,fees,executed_at,created_by)
        SELECT tenant_id,portfolio_id,$1,$2,market,'LEGACY',currency,side,quantity,price,fees,executed_at,created_by
        FROM saas.portfolio_transactions WHERE id=$3""",
        uuid4(),
        legacy_request,
        original_id,
    )
    result = (await client.get(root + "/holdings", headers=headers("alice"))).json()["items"]
    legacy = next(h for h in result if h["symbol"] == "LEGACY")
    assert legacy["catalog_status"] == "unregistered" and legacy["instrument_id"] is None
    retry = await client.post(
        root + "/transactions",
        headers=headers("alice"),
        json=trade(symbol="LEGACY", client_request_id=str(legacy_request)),
    )
    assert retry.status_code == 200 and retry.json()["instrument_id"] is None
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await admin.execute(
            """INSERT INTO saas.portfolio_transactions
            (tenant_id,portfolio_id,id,client_request_id,market,symbol,currency,side,quantity,price,fees,executed_at,created_by,instrument_id)
            SELECT tenant_id,portfolio_id,$1,$2,market,'WRONG',currency,side,quantity,price,fees,executed_at,created_by,instrument_id
            FROM saas.portfolio_transactions WHERE id=$3""",
            uuid4(),
            uuid4(),
            original_id,
        )


async def test_demo_catalog_and_quotes_require_explicit_enablement(tenant_app):
    client, headers, pool, admin, config = tenant_app
    await import_catalog(
        admin,
        catalog_bytes(symbol="DEMO", is_demo=True, isin=None),
        environment="test",
        allow_demo=True,
    )
    demo_id = str(await admin.fetchval("SELECT id FROM saas.instruments WHERE symbol='DEMO'"))
    path = f"/v1/instruments/{demo_id}"
    assert (await client.get(path, headers=headers("alice"))).status_code == 404
    # A separately configured application exercises the actual lifespan/provider setup.
    demo_config = config.model_copy(update={"allow_demo_market_data": True})
    demo_app = create_app(demo_config, pool=pool, verifier=client._transport.app.state.verifier)
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    async with demo_app.router.lifespan_context(demo_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=demo_app), base_url="http://test"
        ) as demo_client:
            quote = (await demo_client.get(path + "/quote", headers=headers("alice"))).json()
            assert quote["status"] == "demo" and quote["quote"]["mode"] == "demo"
            body = trade(symbol="DEMO")
            response = await demo_client.post(
                root + "/transactions", headers=headers("alice"), json=body
            )
            assert response.status_code == 201 and response.json()["is_demo"]
    # Demo flags on recorded history survive disabling catalog/demo access.
    holding = (await client.get(root + "/holdings", headers=headers("alice"))).json()["items"][0]
    assert holding["is_demo"] and holding["catalog_status"] == "unregistered"
    assert (await client.get(path, headers=headers("alice"))).status_code == 404
    assert (
        await client.post(
            root + "/transactions", headers=headers("alice"), json=trade(symbol="DEMO")
        )
    ).status_code == 409


async def prepare_analytics(tenant_app):
    client, headers, pool, admin, config = tenant_app
    config.allow_demo_market_data = True
    config.enable_paper_trading = True
    await seed_demo(admin, environment="test")
    tenant = await workspace(client, headers, "alice")
    item = await portfolio(client, headers, "alice", tenant)
    instrument = await admin.fetchrow("SELECT * FROM saas.instruments WHERE symbol='DEMO-MA'")
    bar = await admin.fetchrow(
        "SELECT * FROM saas.price_bars WHERE instrument_id=$1 ORDER BY as_of DESC LIMIT 1",
        instrument["id"],
    )
    return tenant, item, instrument, bar


async def test_stored_history_signal_and_reproducible_fx_valuation(tenant_app):
    from decimal import Decimal

    client, headers, pool, admin, config = tenant_app
    tenant, item, instrument, bar = await prepare_analytics(tenant_app)
    root = f"/v1/workspaces/{tenant}/portfolios/{item}"
    payload = trade(
        symbol="DEMO-MA",
        quantity="10",
        price=str(bar["close"]),
        executed_at=bar["as_of"].isoformat(),
    )
    assert (
        await client.post(root + "/transactions", headers=headers("alice"), json=payload)
    ).status_code == 201
    history = (
        await client.get(f"/v1/instruments/{instrument['id']}/history", headers=headers("alice"))
    ).json()
    assert history["quality"] == "demo" and len(history["bars"]) == 61
    signal = (
        await client.get(f"/v1/instruments/{instrument['id']}/signal", headers=headers("alice"))
    ).json()
    assert signal["status"] == "no_anomaly_detected"
    spike = await admin.fetchval("SELECT id FROM saas.instruments WHERE symbol='DEMO-SPIKE'")
    assert (await client.get(f"/v1/instruments/{spike}/signal", headers=headers("alice"))).json()[
        "status"
    ] == "elevated"
    # Fixture portfolio is USD; its MAD position uses a sourced direct MAD/USD rate.
    value = (await client.get(root + "/valuation", headers=headers("alice"))).json()
    assert value["status"] == "complete" and value["is_demo"]
    assert Decimal(value["total_value"]) == 10 * bar["close"] * Decimal("0.1")
    assert value["positions"][0]["allocation_pct"] == "100.000000"
    saved = await client.post(root + "/valuations", headers=headers("alice"), json={})
    assert saved.status_code == 201, saved.text
    sid = saved.json()["snapshot_id"]
    assert (
        await client.get(root + f"/valuations/{sid}", headers=headers("alice"))
    ).json() == saved.json()
    assert (
        await client.get(root + f"/valuations/{sid}", headers=headers("bob"))
    ).status_code == 404
    await admin.execute("DELETE FROM saas.fx_rates")
    incomplete = (await client.get(root + "/valuation", headers=headers("alice"))).json()
    assert incomplete["total_value"] is None and incomplete["status"] == "incomplete"
    await admin.execute(
        "UPDATE saas.price_bars SET open=1e-12,high=1e-12,low=1e-12,close=1e-12 WHERE id=$1",
        bar["id"],
    )
    tiny_quote = await client.get(
        f"/v1/instruments/{instrument['id']}/quote", headers=headers("alice")
    )
    assert tiny_quote.status_code == 200, tiny_quote.text
    assert Decimal(tiny_quote.json()["quote"]["price"]) == Decimal("0.000000000001")
    assert (
        await client.get(root + f"/valuations/{sid}", headers=headers("alice"))
    ).json() == saved.json()


async def test_gaps_staleness_and_calendar_uncertainty_withhold_signals(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant, item, instrument, bar = await prepare_analytics(tenant_app)
    root = f"/v1/instruments/{instrument['id']}"
    await admin.execute("DELETE FROM saas.price_bars WHERE id=$1", bar["id"])
    assert (await client.get(root + "/history", headers=headers("alice"))).json()[
        "quality"
    ] == "gap"
    assert (await client.get(root + "/signal", headers=headers("alice"))).json()[
        "status"
    ] == "insufficient_data"
    await admin.execute(
        "UPDATE saas.instrument_feeds SET max_age_seconds=60 WHERE instrument_id=$1",
        instrument["id"],
    )
    assert (await client.get(root + "/history", headers=headers("alice"))).json()[
        "quality"
    ] == "stale"


async def test_market_import_conflicts_are_atomic_and_data_is_readonly(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant, item, instrument, bar = await prepare_analytics(tenant_app)
    from services.analytics.engine import wire

    batch = {
        "source": "finrisk-demo-v1",
        "is_demo": True,
        "fx": [
            {
                "base_currency": "EUR",
                "quote_currency": "MAD",
                "rate": "11",
                "as_of": bar["as_of"].isoformat(),
            }
        ],
        "bars": [
            wire(
                {
                    "market": "XCAS",
                    "symbol": "DEMO-MA",
                    "currency": "MAD",
                    **{
                        k: bar[k]
                        for k in (
                            "session_date",
                            "as_of",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "adjusted",
                        )
                    },
                }
            )
        ],
    }
    first = json.dumps(batch).encode()
    assert (await import_market(admin, first, environment="test", allow_demo=True))[
        "status"
    ] == "imported"
    assert (await import_market(admin, first, environment="test", allow_demo=True))[
        "status"
    ] == "duplicate"
    batch["bars"][0]["volume"] = "123456"
    with pytest.raises(ValueError, match="Conflicting"):
        await import_market(admin, json.dumps(batch).encode(), environment="test", allow_demo=True)
    with pytest.raises(ValueError, match="non-production"):
        await import_market(admin, first, environment="production", allow_demo=True)
    for table in ("price_bars", "market_sessions", "fx_rates", "valuation_snapshots"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with transaction(pool, Identity(config.oidc_issuer, "alice"), UUID(tenant)) as (
                conn,
                _,
                _role,
            ):
                await conn.execute(f"DELETE FROM saas.{table}")


async def test_paper_order_cash_holdings_retry_concurrency_and_isolation(tenant_app):
    from decimal import Decimal

    client, headers, pool, admin, config = tenant_app
    tenant, item, instrument, bar = await prepare_analytics(tenant_app)
    root = f"/v1/workspaces/{tenant}/paper-accounts"
    account = (await client.post(root, headers=headers("alice"), json={"currency": "MAD"})).json()
    path = root + f"/{account['id']}"
    assert (
        await client.post(root, headers=headers("alice"), json={"currency": "MAD"})
    ).status_code == 200
    body = {
        "client_request_id": str(uuid4()),
        "instrument_id": str(instrument["id"]),
        "price_bar_id": str(bar["id"]),
        "quantity": "10",
        "side": "buy",
    }
    results = await asyncio.gather(
        *[client.post(path + "/orders", headers=headers("alice"), json=body) for _ in range(2)]
    )
    assert sorted(r.status_code for r in results) == [200, 201]
    assert all(r.json()["status"] == "filled" for r in results)
    account = (await client.get(path, headers=headers("alice"))).json()
    assert Decimal(account["cash"]) == 100000 - 10 * bar["close"]
    assert Decimal(account["positions"][0]["quantity"]) == 10
    conflict = await client.post(
        path + "/orders", headers=headers("alice"), json={**body, "quantity": "11"}
    )
    assert conflict.status_code == 409
    sells = await asyncio.gather(
        *[
            client.post(
                path + "/orders",
                headers=headers("alice"),
                json={**body, "client_request_id": str(uuid4()), "side": "sell"},
            )
            for _ in range(2)
        ]
    )
    assert sorted(r.json()["status"] for r in sells) == ["filled", "rejected"]
    assert Decimal((await client.get(path, headers=headers("alice"))).json()["cash"]) == 100000
    assert (await client.get(path, headers=headers("bob"))).status_code == 404
    assert (
        await client.post(path + "/orders", headers=headers("bob"), json=body)
    ).status_code == 404
    assert await admin.fetchval("SELECT count(*) FROM saas.portfolio_transactions") == 0
    assert (
        await client.post(f"/v1/workspaces/{tenant}/live-orders", headers=headers("alice"), json={})
    ).status_code == 501


async def test_paper_viewer_and_rejected_funds_and_unavailable_price(tenant_app):
    client, headers, pool, admin, config = tenant_app
    tenant, item, instrument, bar = await prepare_analytics(tenant_app)
    root = f"/v1/workspaces/{tenant}/paper-accounts"
    account = (await client.post(root, headers=headers("alice"), json={"currency": "MAD"})).json()
    path = root + f"/{account['id']}"
    user = (await client.get("/v1/me", headers=headers("bob"))).json()["id"]
    await admin.execute(
        "INSERT INTO saas.memberships VALUES($1,$2,'viewer',now())", UUID(tenant), UUID(user)
    )
    body = {
        "client_request_id": str(uuid4()),
        "instrument_id": str(instrument["id"]),
        "price_bar_id": str(bar["id"]),
        "side": "buy",
        "quantity": "999999",
    }
    assert (
        await client.post(path + "/orders", headers=headers("bob"), json=body)
    ).status_code == 403
    rejected = await client.post(path + "/orders", headers=headers("alice"), json=body)
    assert rejected.json()["status"] == "rejected" and rejected.json()["price"] is None
    assert (await client.get(path, headers=headers("bob"))).json()["cash"] == "100000"
    assert (
        await client.post(
            path + "/orders",
            headers=headers("alice"),
            json={**body, "client_request_id": str(uuid4()), "price_bar_id": str(uuid4())},
        )
    ).status_code == 409
    config.enable_paper_trading = False
    assert (await client.get(root, headers=headers("alice"))).status_code == 404


async def test_dashboard_static_security_and_dev_login_default_off(tenant_app):
    client, headers, pool, admin, config = tenant_app
    response = await client.get("/")
    assert response.status_code == 200 and "FinRisk Sentinel" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert (await client.get("/assets/app.js")).status_code == 200
    assert (await client.post("/v1/dev-login", json={"user": "alice"})).status_code == 404
