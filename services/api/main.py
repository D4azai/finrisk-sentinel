import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

import aiohttp
import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.api.analytics import register_analytics
from services.api.auth import TokenVerifier, unauthorized
from services.api.database import audit, open_pool, transaction
from services.api.instruments import register_instruments
from services.api.ledger import register_ledger, require_portfolio
from services.api.models import (
    PortfolioCreate,
    PortfolioPage,
    PortfolioUpdate,
    PortfolioView,
    WorkspaceCreate,
    WorkspacePage,
    WorkspaceView,
)
from services.api.paper import register_paper
from services.api.settings import APISettings
from services.api.web import register_web
from services.instruments.providers import DemoQuoteProvider

bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


async def authenticated(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    return await request.app.state.verifier.verify(credentials.credentials)


def require_write(role, *, delete=False):
    allowed = {"owner", "admin"} if delete else {"owner", "admin", "member"}
    if role not in allowed:
        raise HTTPException(403, "Membership does not allow this operation")


class BodyLimit:
    """Bound JSON bodies before buffering, including streamed/chunked requests."""

    def __init__(self, app, limit=16384):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PATCH", "PUT"}:
            return await self.app(scope, receive, send)
        data = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    data.extend(message.get("body", b""))
                    if len(data) > self.limit:
                        response = JSONResponse(
                            {"detail": "Request body too large"}, status_code=413
                        )
                        return await response(scope, receive, send)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            response = JSONResponse({"detail": "Request body timed out"}, status_code=408)
            return await response(scope, receive, send)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(data), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings=None, *, pool=None, verifier=None):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or APISettings()
        app.state.settings = config
        app.state.quote_provider = (
            DemoQuoteProvider(environment=config.environment, enabled=True)
            if config.allow_demo_market_data
            else None
        )
        app.state.pool = pool or await open_pool(config)
        try:
            async with aiohttp.ClientSession() as session:
                app.state.http = session
                app.state.verifier = verifier or TokenVerifier(config, session)
                yield
        finally:
            if pool is None:
                try:
                    async with asyncio.timeout(10):
                        await app.state.pool.close()
                except TimeoutError:
                    app.state.pool.terminate()

    app = FastAPI(title="FinRisk Sentinel API", version="0.3.0", lifespan=lifespan)
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def request_context(request, call_next):
        request_id = str(uuid4())
        try:
            response = await call_next(request)
        except (asyncpg.PostgresError, asyncpg.InterfaceError, TimeoutError):
            logger.error("API database request failed", extra={"error_type": "database"})
            response = JSONResponse({"detail": "Service temporarily unavailable"}, status_code=503)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/live", include_in_schema=False)
    async def live():
        return {"alive": True}

    @app.get("/ready", include_in_schema=False)
    async def ready(request: Request):
        async with request.app.state.pool.acquire(timeout=3) as connection:
            await connection.fetchval("SELECT 1")
        return {"ready": True}

    @app.get("/v1/me")
    async def me(request: Request, identity=Depends(authenticated)):
        async with transaction(request.app.state.pool, identity) as (_, user, _role):
            return {"id": user}

    @app.post("/v1/workspaces", status_code=201, response_model=WorkspaceView)
    async def create_workspace(
        body: WorkspaceCreate, request: Request, identity=Depends(authenticated)
    ):
        async with transaction(request.app.state.pool, identity) as (connection, user, _role):
            tenant = await connection.fetchval("SELECT saas.create_workspace($1)", body.name)
            await connection.execute("SELECT set_config('app.tenant_id',$1,true)", str(tenant))
            await audit(connection, tenant, user, "workspace.created", tenant)
            return dict(
                await connection.fetchrow(
                    "SELECT id,name,created_at,'owner' AS role FROM saas.workspaces WHERE id=$1",
                    tenant,
                )
            )

    @app.get("/v1/workspaces", response_model=WorkspacePage)
    async def list_workspaces(
        request: Request,
        cursor: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity) as (connection, user, _role):
            rows = await connection.fetch(
                """SELECT w.id,w.name,w.created_at,m.role FROM saas.workspaces w
                   JOIN saas.memberships m ON m.tenant_id=w.id WHERE m.user_id=$1
                   AND ($2::uuid IS NULL OR w.id>$2) ORDER BY w.id LIMIT $3""",
                user,
                cursor,
                limit + 1,
            )
            return {
                "items": [dict(r) for r in rows[:limit]],
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
            }

    @app.get("/v1/workspaces/{tenant_id}", response_model=WorkspaceView)
    async def workspace(tenant_id: UUID, request: Request, identity=Depends(authenticated)):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            _,
            role,
        ):
            row = dict(
                await connection.fetchrow(
                    "SELECT id,name,created_at FROM saas.workspaces WHERE id=$1", tenant_id
                )
            )
            return {**row, "role": role}

    @app.post(
        "/v1/workspaces/{tenant_id}/portfolios", status_code=201, response_model=PortfolioView
    )
    async def create_portfolio(
        tenant_id: UUID, body: PortfolioCreate, request: Request, identity=Depends(authenticated)
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            user,
            role,
        ):
            require_write(role)
            row = await connection.fetchrow(
                """INSERT INTO saas.portfolios(tenant_id,id,name,base_currency,created_by)
                   VALUES($1,$2,$3,$4,$5) RETURNING *""",
                tenant_id,
                uuid4(),
                body.name,
                body.base_currency,
                user,
            )
            await audit(connection, tenant_id, user, "portfolio.created", row["id"])
            return dict(row)

    @app.get("/v1/workspaces/{tenant_id}/portfolios", response_model=PortfolioPage)
    async def list_portfolios(
        tenant_id: UUID,
        request: Request,
        cursor: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            _,
            _role,
        ):
            rows = await connection.fetch(
                """SELECT * FROM saas.portfolios WHERE tenant_id=$1
                   AND ($2::uuid IS NULL OR id>$2) ORDER BY id LIMIT $3""",
                tenant_id,
                cursor,
                limit + 1,
            )
            return {
                "items": [dict(r) for r in rows[:limit]],
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
            }

    @app.get("/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}", response_model=PortfolioView)
    async def get_portfolio(
        tenant_id: UUID, portfolio_id: UUID, request: Request, identity=Depends(authenticated)
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            _,
            _role,
        ):
            row = await connection.fetchrow(
                "SELECT * FROM saas.portfolios WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                portfolio_id,
            )
            if row is None:
                raise HTTPException(404, "Portfolio not found")
            return dict(row)

    @app.patch("/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}", response_model=PortfolioView)
    async def update_portfolio(
        tenant_id: UUID,
        portfolio_id: UUID,
        body: PortfolioUpdate,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            user,
            role,
        ):
            require_write(role)
            row = await connection.fetchrow(
                """UPDATE saas.portfolios SET name=$3,version=version+1,updated_at=now()
                   WHERE tenant_id=$1 AND id=$2 AND version=$4 RETURNING *""",
                tenant_id,
                portfolio_id,
                body.name,
                body.version,
            )
            if row is None:
                exists = await connection.fetchval(
                    "SELECT 1 FROM saas.portfolios WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    portfolio_id,
                )
                raise HTTPException(
                    409 if exists else 404, "Version conflict" if exists else "Portfolio not found"
                )
            await audit(connection, tenant_id, user, "portfolio.updated", portfolio_id)
            return dict(row)

    @app.delete("/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}", status_code=204)
    async def delete_portfolio(
        tenant_id: UUID, portfolio_id: UUID, request: Request, identity=Depends(authenticated)
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            user,
            role,
        ):
            require_write(role, delete=True)
            await require_portfolio(connection, tenant_id, portfolio_id, lock=True)
            has_history = await connection.fetchval(
                "SELECT 1 FROM saas.portfolio_transactions WHERE tenant_id=$1 AND portfolio_id=$2 LIMIT 1",
                tenant_id,
                portfolio_id,
            )
            if has_history:
                raise HTTPException(409, "Portfolios with transaction history cannot be deleted")
            if await connection.fetchval(
                "SELECT 1 FROM saas.valuation_snapshots WHERE tenant_id=$1 AND portfolio_id=$2 LIMIT 1",
                tenant_id,
                portfolio_id,
            ):
                raise HTTPException(409, "Portfolios with saved valuations cannot be deleted")
            deleted = await connection.fetchval(
                "DELETE FROM saas.portfolios WHERE tenant_id=$1 AND id=$2 RETURNING id",
                tenant_id,
                portfolio_id,
            )
            if deleted is None:
                raise HTTPException(404, "Portfolio not found")
            await audit(connection, tenant_id, user, "portfolio.deleted", portfolio_id)
        return Response(status_code=204)

    register_ledger(app, authenticated, require_write)
    register_instruments(app, authenticated)
    register_analytics(app, authenticated, require_write)
    register_paper(app, authenticated, require_write)
    register_web(app)
    return app


app = create_app()
