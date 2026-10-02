import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from services.api.database import transaction


class PlanView(BaseModel):
    code: str
    version: int
    name: str
    entitlements: dict[str, int | bool]


class SubscriptionView(BaseModel):
    plan: PlanView
    status: Literal["trialing", "active", "grace", "past_due", "canceled"]
    current_period_end: datetime | None
    grace_until: datetime | None
    cancel_at_period_end: bool
    usage: dict[str, int]


async def require_quota(connection, tenant_id: UUID, quota: str):
    row = await connection.fetchrow(
        "SELECT * FROM saas.check_workspace_quota($1,$2)", tenant_id, quota
    )
    if not row["allowed"]:
        label = quota.replace("_", " ")
        raise HTTPException(
            403,
            f"Plan limit reached for {label} ({row['current_usage']}/{row['quota_limit']})",
        )


def register_billing(app, authenticated):
    @app.get("/v1/plans", response_model=list[PlanView])
    async def plans(request: Request, identity=Depends(authenticated)):
        async with transaction(request.app.state.pool, identity) as (connection, _, _):
            rows = await connection.fetch(
                """SELECT plan_code AS code,version,name,entitlements
                   FROM saas.plan_versions WHERE active ORDER BY plan_code,version DESC"""
            )
            return [{**dict(row), "entitlements": decoded(row["entitlements"])} for row in rows]

    @app.get("/v1/workspaces/{tenant_id}/subscription", response_model=SubscriptionView)
    async def subscription(tenant_id: UUID, request: Request, identity=Depends(authenticated)):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            _,
            _,
        ):
            row = await connection.fetchrow(
                """SELECT s.status,s.current_period_end,s.grace_until,s.cancel_at_period_end,
                          p.plan_code AS code,p.version,p.name,p.entitlements
                   FROM saas.workspace_subscriptions s JOIN saas.plan_versions p
                     ON (p.plan_code,p.version)=(s.plan_code,s.plan_version)
                   WHERE s.tenant_id=$1""",
                tenant_id,
            )
            if row is None:
                raise HTTPException(503, "Workspace subscription is unavailable")
            usage = await usage_snapshot(connection, tenant_id)
            return {
                "plan": {
                    "code": row["code"],
                    "version": row["version"],
                    "name": row["name"],
                    "entitlements": decoded(row["entitlements"]),
                },
                "status": row["status"],
                "current_period_end": row["current_period_end"],
                "grace_until": row["grace_until"],
                "cancel_at_period_end": row["cancel_at_period_end"],
                "usage": usage,
            }


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def usage_snapshot(connection, tenant_id):
    row = await connection.fetchrow(
        """SELECT
          (SELECT count(*) FROM saas.memberships WHERE tenant_id=$1) AS seats,
          (SELECT count(*) FROM saas.portfolios WHERE tenant_id=$1) AS portfolios,
          (SELECT count(*) FROM saas.watchlist_items WHERE tenant_id=$1) AS watchlist_instruments,
          (SELECT count(*) FROM saas.risk_scan_runs WHERE tenant_id=$1
             AND created_at>=date_trunc('month',now())) AS risk_scans_monthly""",
        tenant_id,
    )
    return {key: value for key, value in dict(row).items()}
