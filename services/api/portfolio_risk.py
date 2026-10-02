import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field

from services.analytics.portfolio_risk import analyze_portfolio_risk
from services.api.database import audit, transaction
from services.api.models import StrictBody


class RiskLabSettings(StrictBody):
    confidence: Literal["0.95", "0.99"] = "0.95"
    lookback: int = Field(default=252, ge=31, le=366, strict=True)


def register_portfolio_risk(app, authenticated, require_write):
    root = "/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}"

    async def calculate(request, identity, tenant_id, portfolio_id, settings, save):
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
                payload = await analyze_portfolio_risk(
                    conn,
                    tenant_id,
                    portfolio,
                    datetime.now(UTC),
                    Decimal(settings.confidence),
                    settings.lookback,
                )
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            if save:
                if not payload["data_fingerprint"]:
                    raise HTTPException(422, "Risk analysis needs sufficient data before it can be saved")
                snapshot_id = uuid4()
                payload["snapshot_id"] = str(snapshot_id)
                await conn.execute(
                    """INSERT INTO saas.portfolio_risk_snapshots
                    (tenant_id,portfolio_id,id,portfolio_version,method_version,parameters,
                     data_fingerprint,payload,created_by)
                    VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8::jsonb,$9)""",
                    tenant_id,
                    portfolio_id,
                    snapshot_id,
                    portfolio["version"],
                    payload["method_version"],
                    json.dumps(payload["parameters"]),
                    payload["data_fingerprint"],
                    json.dumps(payload),
                    user,
                )
                await audit(conn, tenant_id, user, "portfolio.risk_snapshot_saved", snapshot_id)
            return payload

    @app.get(root + "/risk-lab")
    async def risk_lab(
        tenant_id: UUID,
        portfolio_id: UUID,
        request: Request,
        confidence: Literal["0.95", "0.99"] = Query("0.95"),
        lookback: int = Query(252, ge=31, le=366),
        identity=Depends(authenticated),
    ):
        return await calculate(
            request,
            identity,
            tenant_id,
            portfolio_id,
            RiskLabSettings(confidence=confidence, lookback=lookback),
            False,
        )

    @app.post(root + "/risk-lab/snapshots", status_code=201)
    async def save_risk_lab(
        tenant_id: UUID,
        portfolio_id: UUID,
        body: RiskLabSettings,
        request: Request,
        identity=Depends(authenticated),
    ):
        return await calculate(request, identity, tenant_id, portfolio_id, body, True)

    @app.get(root + "/risk-lab/snapshots/{snapshot_id}")
    async def risk_lab_snapshot(
        tenant_id: UUID,
        portfolio_id: UUID,
        snapshot_id: UUID,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (conn, _, _role):
            payload = await conn.fetchval(
                """SELECT payload FROM saas.portfolio_risk_snapshots
                WHERE tenant_id=$1 AND portfolio_id=$2 AND id=$3""",
                tenant_id,
                portfolio_id,
                snapshot_id,
            )
            if payload is None:
                raise HTTPException(404, "Risk snapshot not found")
            return json.loads(payload)
