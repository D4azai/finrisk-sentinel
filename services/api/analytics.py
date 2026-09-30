import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request

from services.analytics.engine import detect_anomalies, load_history, value_portfolio, wire
from services.api.database import audit, transaction


def register_analytics(app, authenticated, require_write):
    @app.get("/v1/instruments/{instrument_id}/history")
    async def history(
        instrument_id: UUID,
        request: Request,
        limit: int = Query(61, ge=1, le=366),
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
            isolation="repeatable_read",
        ) as (conn, _, _role):
            instrument = await conn.fetchrow(
                "SELECT * FROM saas.instruments WHERE id=$1", instrument_id
            )
            if not instrument:
                raise HTTPException(404, "Instrument not found")
            return wire(await load_history(conn, instrument, datetime.now(UTC), limit))

    @app.get("/v1/instruments/{instrument_id}/signal")
    async def signal(instrument_id: UUID, request: Request, identity=Depends(authenticated)):
        async with transaction(
            request.app.state.pool,
            identity,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
            isolation="repeatable_read",
        ) as (conn, _, _role):
            instrument = await conn.fetchrow(
                "SELECT * FROM saas.instruments WHERE id=$1", instrument_id
            )
            if not instrument:
                raise HTTPException(404, "Instrument not found")
            return detect_anomalies(await load_history(conn, instrument, datetime.now(UTC)))

    async def compute(request, identity, tenant_id, portfolio_id, save):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
            isolation="repeatable_read",
        ) as (conn, user, role):
            portfolio = await conn.fetchrow(
                "SELECT * FROM saas.portfolios WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                portfolio_id,
            )
            if not portfolio:
                raise HTTPException(404, "Portfolio not found")
            if save:
                require_write(role)
            try:
                payload = await value_portfolio(conn, tenant_id, portfolio, datetime.now(UTC))
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            if save:
                snapshot_id = uuid4()
                payload["snapshot_id"] = str(snapshot_id)
                await conn.execute(
                    """INSERT INTO saas.valuation_snapshots
                    (tenant_id,portfolio_id,id,portfolio_version,created_by,payload) VALUES($1,$2,$3,$4,$5,$6::jsonb)""",
                    tenant_id,
                    portfolio_id,
                    snapshot_id,
                    portfolio["version"],
                    user,
                    json.dumps(payload),
                )
                await audit(conn, tenant_id, user, "portfolio.valuation_saved", snapshot_id)
            return payload

    root = "/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}"

    @app.get(root + "/valuation")
    async def valuation(
        tenant_id: UUID, portfolio_id: UUID, request: Request, identity=Depends(authenticated)
    ):
        return await compute(request, identity, tenant_id, portfolio_id, False)

    @app.post(root + "/valuations", status_code=201)
    async def save_valuation(
        tenant_id: UUID, portfolio_id: UUID, request: Request, identity=Depends(authenticated)
    ):
        return await compute(request, identity, tenant_id, portfolio_id, True)

    @app.get(root + "/valuations/{snapshot_id}")
    async def snapshot(
        tenant_id: UUID,
        portfolio_id: UUID,
        snapshot_id: UUID,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (conn, _, _role):
            payload = await conn.fetchval(
                "SELECT payload FROM saas.valuation_snapshots WHERE tenant_id=$1 AND portfolio_id=$2 AND id=$3",
                tenant_id,
                portfolio_id,
                snapshot_id,
            )
            if payload is None:
                raise HTTPException(404, "Valuation not found")
            return json.loads(payload)
