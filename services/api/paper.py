from datetime import UTC, datetime
from decimal import localcontext
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import Field

from services.analytics.engine import load_history, wire
from services.api.database import audit, transaction
from services.api.models import StrictBody
from services.common.decimal_types import Amount


class PaperAccountCreate(StrictBody):
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class PaperOrderCreate(StrictBody):
    client_request_id: UUID
    instrument_id: UUID
    price_bar_id: UUID
    side: Literal["buy", "sell"]
    quantity: Amount = Field(gt=0)


def enabled(request):
    config = request.app.state.settings
    if (
        not config.enable_paper_trading
        or not config.allow_demo_market_data
        or config.environment == "production"
    ):
        raise HTTPException(404, "Paper trading is not enabled")


def register_paper(app, authenticated, require_write):
    root = "/v1/workspaces/{tenant_id}/paper-accounts"

    @app.post(root, status_code=201)
    async def create_account(
        tenant_id: UUID,
        body: PaperAccountCreate,
        request: Request,
        response: Response,
        identity=Depends(authenticated),
    ):
        enabled(request)
        async with transaction(
            request.app.state.pool, identity, tenant_id, allow_demo_market_data=True
        ) as (conn, user, role):
            require_write(role)
            row = await conn.fetchrow(
                """INSERT INTO saas.paper_accounts(tenant_id,id,currency,created_by)
                VALUES($1,$2,$3,$4) ON CONFLICT(tenant_id,currency) DO NOTHING RETURNING *""",
                tenant_id,
                uuid4(),
                body.currency,
                user,
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM saas.paper_accounts WHERE tenant_id=$1 AND currency=$2",
                    tenant_id,
                    body.currency,
                )
                response.status_code = 200
            else:
                await audit(conn, tenant_id, user, "paper.account_created", row["id"])
            return wire({**dict(row), "simulation": True})

    @app.get(root)
    async def accounts(
        tenant_id: UUID,
        request: Request,
        cursor: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        enabled(request)
        async with transaction(request.app.state.pool, identity, tenant_id) as (conn, _, _role):
            rows = await conn.fetch(
                "SELECT * FROM saas.paper_accounts WHERE tenant_id=$1 AND ($2::uuid IS NULL OR id>$2) ORDER BY id LIMIT $3",
                tenant_id,
                cursor,
                limit + 1,
            )
            return wire(
                {
                    "simulation": True,
                    "items": [dict(r) for r in rows[:limit]],
                    "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
                }
            )

    @app.get(root + "/{account_id}")
    async def account(
        tenant_id: UUID, account_id: UUID, request: Request, identity=Depends(authenticated)
    ):
        enabled(request)
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=True,
            isolation="repeatable_read",
        ) as (conn, _, _role):
            row = await conn.fetchrow(
                "SELECT * FROM saas.paper_accounts WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                account_id,
            )
            if row is None:
                raise HTTPException(404, "Paper account not found")
            positions = await conn.fetch(
                """SELECT instrument_id,sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END) AS quantity
                FROM saas.paper_orders WHERE tenant_id=$1 AND account_id=$2 AND status='filled'
                GROUP BY instrument_id HAVING sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END)<>0
                ORDER BY instrument_id LIMIT 501""",
                tenant_id,
                account_id,
            )
            if len(positions) > 500:
                raise HTTPException(422, "Paper account exceeds 500-position display limit")
            return wire(
                {**dict(row), "simulation": True, "positions": [dict(r) for r in positions]}
            )

    @app.get(root + "/{account_id}/orders")
    async def orders(
        tenant_id: UUID,
        account_id: UUID,
        request: Request,
        cursor: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        enabled(request)
        async with transaction(request.app.state.pool, identity, tenant_id) as (conn, _, _role):
            if not await conn.fetchval(
                "SELECT 1 FROM saas.paper_accounts WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                account_id,
            ):
                raise HTTPException(404, "Paper account not found")
            rows = await conn.fetch(
                """SELECT * FROM saas.paper_orders WHERE tenant_id=$1 AND account_id=$2
                AND ($3::uuid IS NULL OR id>$3) ORDER BY id LIMIT $4""",
                tenant_id,
                account_id,
                cursor,
                limit + 1,
            )
            return wire(
                {
                    "simulation": True,
                    "items": [dict(r) for r in rows[:limit]],
                    "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
                }
            )

    @app.post(root + "/{account_id}/orders", status_code=201)
    async def submit(
        tenant_id: UUID,
        account_id: UUID,
        body: PaperOrderCreate,
        request: Request,
        response: Response,
        identity=Depends(authenticated),
    ):
        enabled(request)
        async with transaction(
            request.app.state.pool, identity, tenant_id, allow_demo_market_data=True
        ) as (conn, user, role):
            require_write(role)
            account = await conn.fetchrow(
                "SELECT * FROM saas.paper_accounts WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                tenant_id,
                account_id,
            )
            if account is None:
                raise HTTPException(404, "Paper account not found")
            prior = await conn.fetchrow(
                "SELECT * FROM saas.paper_orders WHERE tenant_id=$1 AND account_id=$2 AND client_request_id=$3",
                tenant_id,
                account_id,
                body.client_request_id,
            )
            if prior:
                if any(prior[k] != v for k, v in body.model_dump().items()):
                    raise HTTPException(409, "Request ID already used for another order")
                response.status_code = 200
                return wire({**dict(prior), "simulation": True})
            instrument = await conn.fetchrow(
                "SELECT * FROM saas.instruments WHERE id=$1", body.instrument_id
            )
            if not instrument or not instrument["is_demo"]:
                raise HTTPException(409, "Simulation requires a demo instrument")
            history = await load_history(conn, instrument, datetime.now(UTC), limit=1)
            if not history["bars"] or history["bars"][-1]["id"] != body.price_bar_id:
                raise HTTPException(
                    409, "Reference price changed or is unavailable; refresh before submitting"
                )
            bar = history["bars"][-1]
            reason = None
            if history["quality"] != "demo":
                reason = "Market data is stale or incomplete"
            elif not instrument["active"]:
                reason = "Instrument is inactive"
            elif instrument["currency"] != account["currency"]:
                reason = "Account and instrument currencies differ"
            holding = await conn.fetchval(
                """SELECT coalesce(sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END),0)
                FROM saas.paper_orders WHERE tenant_id=$1 AND account_id=$2 AND instrument_id=$3 AND status='filled'""",
                tenant_id,
                account_id,
                body.instrument_id,
            )
            with localcontext() as context:
                context.prec = 128
                cost = body.quantity * bar["close"]
                if reason is None and body.side == "buy" and cost > account["cash"]:
                    reason = "Insufficient simulated cash"
                if reason is None and body.side == "sell" and body.quantity > holding:
                    reason = "Insufficient simulated holdings"
                new_cash = account["cash"] + (-cost if body.side == "buy" else cost)
                if reason is None and new_cash >= 10**30:
                    reason = "Simulation cash limit exceeded"
            status = "rejected" if reason else "filled"
            row = await conn.fetchrow(
                """INSERT INTO saas.paper_orders
                (tenant_id,account_id,id,client_request_id,instrument_id,price_bar_id,side,quantity,status,price,reason,created_by)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING *""",
                tenant_id,
                account_id,
                uuid4(),
                body.client_request_id,
                body.instrument_id,
                body.price_bar_id,
                body.side,
                body.quantity,
                status,
                bar["close"] if status == "filled" else None,
                reason or "Simulated fill at last completed daily close; zero fees and slippage",
                user,
            )
            if status == "filled":
                await conn.execute(
                    "UPDATE saas.paper_accounts SET cash=$3 WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    account_id,
                    new_cash,
                )
            await audit(conn, tenant_id, user, "paper.order_" + status, row["id"])
            return wire({**dict(row), "simulation": True})

    @app.post("/v1/workspaces/{tenant_id}/live-orders")
    async def live_orders(tenant_id: UUID, request: Request, identity=Depends(authenticated)):
        async with transaction(request.app.state.pool, identity, tenant_id):
            raise HTTPException(501, "No live broker is connected; real orders cannot be submitted")
