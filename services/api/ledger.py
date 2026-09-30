from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request, Response

from services.api.database import audit, transaction
from services.api.ledger_models import (
    HoldingsPage,
    TransactionCreate,
    TransactionPage,
    TransactionView,
)


async def require_portfolio(connection, tenant, portfolio, *, lock=False):
    row = await connection.fetchrow(
        "SELECT id FROM saas.portfolios WHERE tenant_id=$1 AND id=$2"
        + (" FOR UPDATE" if lock else ""),
        tenant,
        portfolio,
    )
    if row is None:
        raise HTTPException(404, "Portfolio not found")


def register_ledger(app, authenticated, require_write):
    root = "/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}"

    @app.post(root + "/transactions", status_code=201, response_model=TransactionView)
    async def record_trade(
        tenant_id: UUID,
        portfolio_id: UUID,
        body: TransactionCreate,
        request: Request,
        response: Response,
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (conn, user, role):
            require_write(role)
            # Serialize holdings checks, retries, and deletes for this portfolio.
            await require_portfolio(conn, tenant_id, portfolio_id, lock=True)
            previous = await conn.fetchrow(
                """SELECT * FROM saas.portfolio_transactions
                   WHERE tenant_id=$1 AND portfolio_id=$2 AND client_request_id=$3""",
                tenant_id,
                portfolio_id,
                body.client_request_id,
            )
            if previous:
                if any(previous[key] != value for key, value in body.model_dump().items()):
                    raise HTTPException(409, "Request ID already used for a different transaction")
                response.status_code = 200
                return dict(previous)
            listing = await conn.fetchrow(
                "SELECT id,is_demo FROM saas.instruments WHERE market=$1 AND symbol=$2 AND currency=$3",
                body.market,
                body.symbol,
                body.currency,
            )
            if listing is None:
                raise HTTPException(
                    409, "Listing not in the available catalog; check exchange, ticker and currency"
                )
            state = await conn.fetchrow(
                """SELECT max(executed_at) AS latest, min(currency) AS currency,
                   coalesce(sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END),0) AS quantity
                   FROM saas.portfolio_transactions
                   WHERE tenant_id=$1 AND portfolio_id=$2 AND market=$3 AND symbol=$4""",
                tenant_id,
                portfolio_id,
                body.market,
                body.symbol,
            )
            if state["currency"] and state["currency"] != body.currency:
                raise HTTPException(409, "Instrument currency differs from its recorded history")
            if state["latest"] and body.executed_at < state["latest"]:
                raise HTTPException(409, "Record trades in execution order for each instrument")
            if body.side == "sell" and body.quantity > state["quantity"]:
                raise HTTPException(409, "Insufficient recorded holdings")
            row = await conn.fetchrow(
                """INSERT INTO saas.portfolio_transactions
                   (tenant_id,portfolio_id,id,client_request_id,market,symbol,currency,
                    side,quantity,price,fees,executed_at,created_by,instrument_id,is_demo)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) RETURNING *""",
                tenant_id,
                portfolio_id,
                uuid4(),
                body.client_request_id,
                body.market,
                body.symbol,
                body.currency,
                body.side,
                body.quantity,
                body.price,
                body.fees,
                body.executed_at,
                user,
                listing["id"],
                listing["is_demo"],
            )
            await conn.execute(
                """UPDATE saas.portfolios SET version=version+1,updated_at=now()
                   WHERE tenant_id=$1 AND id=$2""",
                tenant_id,
                portfolio_id,
            )
            await audit(conn, tenant_id, user, "portfolio.transaction_recorded", row["id"])
            return dict(row)

    @app.get(root + "/transactions", response_model=TransactionPage)
    async def list_trades(
        tenant_id: UUID,
        portfolio_id: UUID,
        request: Request,
        cursor: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (conn, _, _role):
            await require_portfolio(conn, tenant_id, portfolio_id)
            rows = await conn.fetch(
                """SELECT * FROM saas.portfolio_transactions
                   WHERE tenant_id=$1 AND portfolio_id=$2 AND ($3::uuid IS NULL OR id>$3)
                   ORDER BY id LIMIT $4""",
                tenant_id,
                portfolio_id,
                cursor,
                limit + 1,
            )
            return {
                "items": [dict(r) for r in rows[:limit]],
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
            }

    @app.get(root + "/holdings", response_model=HoldingsPage)
    async def holdings(
        tenant_id: UUID,
        portfolio_id: UUID,
        request: Request,
        cursor: str | None = Query(
            None, max_length=41, pattern=r"^[A-Z0-9]{4}:[A-Z0-9][A-Z0-9._-]{0,31}:[A-Z]{3}$"
        ),
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (conn, _, _role):
            await require_portfolio(conn, tenant_id, portfolio_id)
            rows = await conn.fetch(
                """SELECT h.*,i.id AS instrument_id,i.name AS instrument_name,i.isin,
                   CASE WHEN i.id IS NULL THEN 'unregistered' ELSE 'registered' END AS catalog_status
                   FROM (SELECT market || ':' || symbol || ':' || currency AS instrument,
                   market,symbol,currency,
                   bool_or(is_demo) AS is_demo,
                   sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END) AS quantity,
                   sum(CASE WHEN side='sell' THEN quantity*price-fees
                       ELSE -quantity*price-fees END) AS net_cash_flow,
                   sum(fees) AS fees,max(executed_at) AS last_executed_at
                   FROM saas.portfolio_transactions WHERE tenant_id=$1 AND portfolio_id=$2
                   AND ($3::text IS NULL OR (market || ':' || symbol || ':' || currency) COLLATE "C" > $3 COLLATE "C")
                   GROUP BY market,symbol,currency
                   ORDER BY (market || ':' || symbol || ':' || currency) COLLATE "C" LIMIT $4) h
                   LEFT JOIN saas.instruments i ON i.market=h.market AND i.symbol=h.symbol AND i.currency=h.currency
                   ORDER BY h.instrument COLLATE "C"
                """,
                tenant_id,
                portfolio_id,
                cursor,
                limit + 1,
            )
            return {
                "items": [dict(r) for r in rows[:limit]],
                "next_cursor": rows[limit - 1]["instrument"] if len(rows) > limit else None,
            }
