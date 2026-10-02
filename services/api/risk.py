import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from services.analytics.engine import detect_anomalies, load_history
from services.api.billing import require_quota
from services.api.database import audit, transaction
from services.api.models import StrictBody


class WatchlistCreate(StrictBody):
    instrument_id: UUID
    alerts_enabled: bool = Field(True, strict=True)


class WatchlistUpdate(StrictBody):
    alerts_enabled: bool = Field(strict=True)


class WatchlistView(BaseModel):
    instrument_id: UUID
    market: str
    symbol: str
    currency: str
    name: str
    is_demo: bool
    alerts_enabled: bool
    created_at: datetime


class RiskScanCreate(StrictBody):
    client_request_id: UUID


class RiskScanView(BaseModel):
    id: UUID
    status: Literal["succeeded"]
    evaluated_count: int
    elevated_count: int
    new_alert_count: int
    created_at: datetime
    completed_at: datetime
    results: list[dict]


class RiskScanHistoryView(BaseModel):
    id: UUID
    status: Literal["running", "succeeded"]
    evaluated_count: int
    elevated_count: int
    new_alert_count: int
    created_at: datetime
    completed_at: datetime | None


class RiskAlertView(BaseModel):
    id: UUID
    instrument_id: UUID
    market: str
    symbol: str
    currency: str
    status: Literal["open", "acknowledged"]
    severity: Literal["elevated"]
    title: str
    evidence: dict
    triggered_at: datetime
    acknowledged_at: datetime | None


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def run_view(row):
    result = decoded(row["result"]) if row["result"] is not None else {"results": []}
    return {
        "id": row["id"],
        "status": row["status"],
        "evaluated_count": row["evaluated_count"],
        "elevated_count": row["elevated_count"],
        "new_alert_count": row["new_alert_count"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "results": result["results"],
    }


def register_risk(app, authenticated, require_write):
    root = "/v1/workspaces/{tenant_id}"

    @app.get(root + "/watchlist", response_model=list[WatchlistView])
    async def list_watchlist(tenant_id: UUID, request: Request, identity=Depends(authenticated)):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (connection, _, _):
            rows = await connection.fetch(
                """SELECT w.instrument_id,i.market,i.symbol,i.currency,i.name,i.is_demo,
                   r.enabled AS alerts_enabled,w.created_at
                   FROM saas.watchlist_items w
                   JOIN saas.instruments i ON i.id=w.instrument_id
                   JOIN saas.alert_rules r ON r.tenant_id=w.tenant_id
                    AND r.instrument_id=w.instrument_id AND r.kind='daily_anomaly'
                   WHERE w.tenant_id=$1 ORDER BY w.created_at,w.instrument_id""",
                tenant_id,
            )
            return [dict(row) for row in rows]

    @app.post(root + "/watchlist", status_code=201, response_model=WatchlistView)
    async def add_watchlist(
        tenant_id: UUID,
        body: WatchlistCreate,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (connection, user, role):
            require_write(role)
            instrument = await connection.fetchrow(
                "SELECT * FROM saas.instruments WHERE id=$1", body.instrument_id
            )
            if instrument is None:
                raise HTTPException(404, "Instrument not found")
            await require_quota(connection, tenant_id, "watchlist_instruments")
            inserted = await connection.fetchval(
                """INSERT INTO saas.watchlist_items(tenant_id,instrument_id,created_by)
                   VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING instrument_id""",
                tenant_id,
                body.instrument_id,
                user,
            )
            if inserted is None:
                raise HTTPException(409, "Instrument is already on the watchlist")
            await connection.execute(
                """INSERT INTO saas.alert_rules(tenant_id,id,instrument_id,enabled,created_by)
                   VALUES($1,$2,$3,$4,$5)""",
                tenant_id,
                uuid4(),
                body.instrument_id,
                body.alerts_enabled,
                user,
            )
            await audit(
                connection, tenant_id, user, "watchlist.instrument_added", body.instrument_id
            )
            return {
                "instrument_id": body.instrument_id,
                "market": instrument["market"],
                "symbol": instrument["symbol"],
                "currency": instrument["currency"],
                "name": instrument["name"],
                "is_demo": instrument["is_demo"],
                "alerts_enabled": body.alerts_enabled,
                "created_at": datetime.now(UTC),
            }

    @app.patch(root + "/watchlist/{instrument_id}", response_model=WatchlistView)
    async def update_watchlist(
        tenant_id: UUID,
        instrument_id: UUID,
        body: WatchlistUpdate,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (connection, user, role):
            require_write(role)
            updated = await connection.fetchval(
                """UPDATE saas.alert_rules SET enabled=$3
                   WHERE tenant_id=$1 AND instrument_id=$2 AND kind='daily_anomaly'
                   RETURNING id""",
                tenant_id,
                instrument_id,
                body.alerts_enabled,
            )
            if updated is None:
                raise HTTPException(404, "Watchlist instrument not found")
            await audit(connection, tenant_id, user, "watchlist.rule_updated", updated)
            row = await connection.fetchrow(
                """SELECT w.instrument_id,i.market,i.symbol,i.currency,i.name,i.is_demo,
                   r.enabled AS alerts_enabled,w.created_at FROM saas.watchlist_items w
                   JOIN saas.instruments i ON i.id=w.instrument_id
                   JOIN saas.alert_rules r ON r.tenant_id=w.tenant_id
                    AND r.instrument_id=w.instrument_id
                   WHERE w.tenant_id=$1 AND w.instrument_id=$2""",
                tenant_id,
                instrument_id,
            )
            return dict(row)

    @app.delete(root + "/watchlist/{instrument_id}", status_code=204)
    async def remove_watchlist(
        tenant_id: UUID,
        instrument_id: UUID,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            user,
            role,
        ):
            require_write(role)
            removed = await connection.fetchval(
                """DELETE FROM saas.watchlist_items
                   WHERE tenant_id=$1 AND instrument_id=$2 RETURNING instrument_id""",
                tenant_id,
                instrument_id,
            )
            if removed is None:
                raise HTTPException(404, "Watchlist instrument not found")
            await audit(connection, tenant_id, user, "watchlist.instrument_removed", instrument_id)
        return Response(status_code=204)

    @app.post(root + "/risk-scans", response_model=RiskScanView)
    async def run_risk_scan(
        tenant_id: UUID,
        body: RiskScanCreate,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (connection, user, role):
            require_write(role)
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", str(tenant_id)
            )
            previous = await connection.fetchrow(
                """SELECT * FROM saas.risk_scan_runs
                   WHERE tenant_id=$1 AND client_request_id=$2""",
                tenant_id,
                body.client_request_id,
            )
            if previous:
                return run_view(previous)
            await require_quota(connection, tenant_id, "risk_scans_monthly")
            rules = await connection.fetch(
                """SELECT r.id AS rule_id,i.* FROM saas.alert_rules r
                   JOIN saas.instruments i ON i.id=r.instrument_id
                   WHERE r.tenant_id=$1 AND r.enabled ORDER BY r.created_at LIMIT 101""",
                tenant_id,
            )
            if len(rules) > 100:
                raise HTTPException(409, "Risk scan is limited to 100 enabled rules")
            run_id = uuid4()
            await connection.execute(
                """INSERT INTO saas.risk_scan_runs
                   (tenant_id,id,client_request_id,status,requested_by)
                   VALUES($1,$2,$3,'running',$4)""",
                tenant_id,
                run_id,
                body.client_request_id,
                user,
            )
            results = []
            elevated = 0
            new_alerts = 0
            evaluated_at = datetime.now(UTC)
            for rule in rules:
                signal = detect_anomalies(await load_history(connection, rule, evaluated_at))
                results.append(
                    {
                        "instrument_id": str(rule["id"]),
                        "market": rule["market"],
                        "symbol": rule["symbol"],
                        "signal": signal,
                    }
                )
                if signal["status"] != "elevated":
                    continue
                elevated += 1
                latest_bar = signal["bar_ids"][-1] if signal["bar_ids"] else "none"
                dedupe = sha256(
                    f"{rule['rule_id']}|{signal['model_version']}|{latest_bar}".encode()
                ).hexdigest()
                alert_id = uuid4()
                inserted = await connection.fetchval(
                    """INSERT INTO saas.risk_alerts
                       (tenant_id,id,rule_id,instrument_id,run_id,dedupe_key,severity,
                        title,evidence,created_by,triggered_at)
                       VALUES($1,$2,$3,$4,$5,$6,'elevated',$7,$8::jsonb,$9,$10)
                       ON CONFLICT(tenant_id,dedupe_key) DO NOTHING RETURNING id""",
                    tenant_id,
                    alert_id,
                    rule["rule_id"],
                    rule["id"],
                    run_id,
                    dedupe,
                    f"Elevated anomaly signal for {rule['symbol']}",
                    json.dumps(signal),
                    user,
                    evaluated_at,
                )
                if inserted:
                    new_alerts += 1
            completed_at = datetime.now(UTC)
            payload = {"model_version": "daily-robust-v1", "results": results}
            row = await connection.fetchrow(
                """UPDATE saas.risk_scan_runs SET status='succeeded',evaluated_count=$3,
                   elevated_count=$4,new_alert_count=$5,result=$6::jsonb,completed_at=$7
                   WHERE tenant_id=$1 AND id=$2 RETURNING *""",
                tenant_id,
                run_id,
                len(results),
                elevated,
                new_alerts,
                json.dumps(payload),
                completed_at,
            )
            await audit(connection, tenant_id, user, "risk.scan_completed", run_id)
            return run_view(row)

    @app.get(root + "/risk-scans", response_model=list[RiskScanHistoryView])
    async def list_risk_scans(
        tenant_id: UUID,
        request: Request,
        limit: int = Query(20, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            _,
            _,
        ):
            rows = await connection.fetch(
                """SELECT * FROM saas.risk_scan_runs WHERE tenant_id=$1
                   ORDER BY created_at DESC LIMIT $2""",
                tenant_id,
                limit,
            )
            return [dict(row) for row in rows]

    @app.get(root + "/alerts", response_model=list[RiskAlertView])
    async def list_alerts(
        tenant_id: UUID,
        request: Request,
        status: Literal["open", "acknowledged"] | None = None,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (connection, _, _):
            rows = await connection.fetch(
                """SELECT a.id,a.instrument_id,i.market,i.symbol,i.currency,a.status,
                   a.severity,a.title,a.evidence,a.triggered_at,a.acknowledged_at
                   FROM saas.risk_alerts a JOIN saas.instruments i ON i.id=a.instrument_id
                   WHERE a.tenant_id=$1 AND ($2::text IS NULL OR a.status=$2)
                   ORDER BY a.triggered_at DESC LIMIT $3""",
                tenant_id,
                status,
                limit,
            )
            return [{**dict(row), "evidence": decoded(row["evidence"])} for row in rows]

    @app.post(root + "/alerts/{alert_id}/acknowledge", response_model=RiskAlertView)
    async def acknowledge_alert(
        tenant_id: UUID,
        alert_id: UUID,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (connection, user, role):
            require_write(role)
            changed = await connection.fetchval(
                """UPDATE saas.risk_alerts SET status='acknowledged',
                   acknowledged_by=$3,acknowledged_at=now()
                   WHERE tenant_id=$1 AND id=$2 AND status='open' RETURNING id""",
                tenant_id,
                alert_id,
                user,
            )
            row = await connection.fetchrow(
                """SELECT a.id,a.instrument_id,i.market,i.symbol,i.currency,a.status,
                   a.severity,a.title,a.evidence,a.triggered_at,a.acknowledged_at
                   FROM saas.risk_alerts a JOIN saas.instruments i ON i.id=a.instrument_id
                   WHERE a.tenant_id=$1 AND a.id=$2""",
                tenant_id,
                alert_id,
            )
            if row is None:
                raise HTTPException(404, "Alert not found")
            if changed:
                await audit(connection, tenant_id, user, "risk.alert_acknowledged", alert_id)
            return {**dict(row), "evidence": decoded(row["evidence"])}
