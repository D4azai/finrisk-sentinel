import csv
import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4, uuid5

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from services.api.database import audit, transaction
from services.api.ledger import record_transaction, require_portfolio
from services.api.ledger_models import TransactionCreate
from services.api.models import StrictBody

REQUIRED_COLUMNS = {"market", "symbol", "currency", "side", "quantity", "price", "executed_at"}
OPTIONAL_COLUMNS = {"fees", "client_request_id"}
MAX_IMPORT_ROWS = 500


class ImportPreviewRequest(StrictBody):
    client_request_id: UUID
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    csv_text: str = Field(min_length=1, max_length=524288)


class ImportRowView(BaseModel):
    row_number: int
    data: dict[str, str]
    errors: list[str]


class ImportPreviewView(BaseModel):
    id: UUID
    client_request_id: UUID
    filename: str | None
    status: Literal["previewed", "committed", "expired"]
    row_count: int
    valid_count: int
    error_count: int
    created_at: datetime
    expires_at: datetime
    committed_at: datetime | None
    rows: list[ImportRowView]


class ImportHistoryView(BaseModel):
    id: UUID
    filename: str | None
    status: Literal["previewed", "committed", "expired"]
    row_count: int
    valid_count: int
    error_count: int
    created_at: datetime
    expires_at: datetime
    committed_at: datetime | None


class ImportCommitView(BaseModel):
    import_id: UUID
    status: Literal["committed"]
    imported_count: int
    portfolio_version: int
    committed_at: datetime


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def row_errors(error: ValidationError) -> list[str]:
    result = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        result.append(f"{location}: {item['msg']}")
    return result


def parse_transactions(csv_text: str, namespace: UUID):
    if "\x00" in csv_text:
        raise HTTPException(422, "CSV contains a null byte")
    try:
        reader = csv.DictReader(io.StringIO(csv_text, newline=""))
        raw_headers = reader.fieldnames
    except csv.Error as exc:
        raise HTTPException(422, f"Invalid CSV: {exc}") from None
    if not raw_headers:
        raise HTTPException(422, "CSV header is required")
    headers = [header.lstrip("\ufeff").strip().lower() for header in raw_headers]
    if len(headers) != len(set(headers)):
        raise HTTPException(422, "CSV headers must be unique")
    missing = REQUIRED_COLUMNS - set(headers)
    unexpected = set(headers) - REQUIRED_COLUMNS - OPTIONAL_COLUMNS
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unexpected:
            details.append("unexpected " + ", ".join(sorted(unexpected)))
        raise HTTPException(422, "CSV columns: " + "; ".join(details))
    reader.fieldnames = headers
    rows = []
    try:
        for row_number, raw in enumerate(reader, start=2):
            if None in raw:
                raise HTTPException(422, f"Row {row_number} has more values than the header")
            data = {key: (value or "").strip() for key, value in raw.items()}
            if not any(data.values()):
                continue
            if len(rows) >= MAX_IMPORT_ROWS:
                raise HTTPException(
                    413,
                    f"Synchronous imports are limited to {MAX_IMPORT_ROWS} transactions; use the background import workflow",
                )
            errors = []
            if any(len(value) > 255 for value in data.values()):
                errors.append("Each CSV field is limited to 255 characters")
            payload = {
                "client_request_id": data.get("client_request_id")
                or str(uuid5(namespace, str(row_number))),
                "market": data.get("market", "").upper(),
                "symbol": data.get("symbol", "").upper(),
                "currency": data.get("currency", "").upper(),
                "side": data.get("side", "").lower(),
                "quantity": data.get("quantity", ""),
                "price": data.get("price", ""),
                "fees": data.get("fees", "0") or "0",
                "executed_at": data.get("executed_at", ""),
            }
            body = None
            if not errors:
                try:
                    body = TransactionCreate.model_validate(payload)
                    payload = body.model_dump(mode="json")
                except ValidationError as exc:
                    errors.extend(row_errors(exc))
            rows.append({"row_number": row_number, "data": payload, "errors": errors, "body": body})
    except csv.Error as exc:
        raise HTTPException(422, f"Invalid CSV: {exc}") from None
    if not rows:
        raise HTTPException(422, "CSV must contain at least one transaction")
    return rows


async def validate_portfolio_state(connection, tenant_id, portfolio_id, rows):
    listings = {
        (row["market"], row["symbol"], row["currency"])
        for row in await connection.fetch("SELECT market,symbol,currency FROM saas.instruments")
    }
    states = {
        (row["market"], row["symbol"]): {
            "currency": row["currency"],
            "latest": row["latest"],
            "quantity": row["quantity"],
        }
        for row in await connection.fetch(
            """SELECT market,symbol,min(currency) AS currency,max(executed_at) AS latest,
               coalesce(sum(CASE WHEN side='buy' THEN quantity ELSE -quantity END),0) AS quantity
               FROM saas.portfolio_transactions WHERE tenant_id=$1 AND portfolio_id=$2
               GROUP BY market,symbol""",
            tenant_id,
            portfolio_id,
        )
    }
    valid_ids = [item["body"].client_request_id for item in rows if item["body"]]
    existing_ids = set()
    if valid_ids:
        existing_ids = {
            row["client_request_id"]
            for row in await connection.fetch(
                """SELECT client_request_id FROM saas.portfolio_transactions
                   WHERE tenant_id=$1 AND portfolio_id=$2
                   AND client_request_id=ANY($3::uuid[])""",
                tenant_id,
                portfolio_id,
                valid_ids,
            )
        }
    seen_ids = set()
    for item in rows:
        body = item["body"]
        if body is None:
            continue
        errors = item["errors"]
        listing = (body.market, body.symbol, body.currency)
        if listing not in listings:
            errors.append("Listing is not in the available instrument catalog")
        if body.client_request_id in existing_ids or body.client_request_id in seen_ids:
            errors.append("Client request ID is already used")
        seen_ids.add(body.client_request_id)
        key = (body.market, body.symbol)
        state = states.setdefault(
            key, {"currency": body.currency, "latest": None, "quantity": Decimal("0")}
        )
        if state["currency"] != body.currency:
            errors.append("Instrument currency differs from its recorded history")
        if state["latest"] and body.executed_at < state["latest"]:
            errors.append("Transactions must be in execution order for each instrument")
        if body.side == "sell" and body.quantity > state["quantity"]:
            errors.append("Insufficient recorded holdings")
        if not errors:
            state["latest"] = body.executed_at
            state["quantity"] += body.quantity if body.side == "buy" else -body.quantity


def effective_status(row, now=None):
    now = now or datetime.now(UTC)
    if row["status"] == "previewed" and row["expires_at"] <= now:
        return "expired"
    return row["status"]


async def preview_payload(connection, row):
    rows = await connection.fetch(
        """SELECT row_number,payload,errors FROM saas.portfolio_transaction_import_rows
           WHERE tenant_id=$1 AND portfolio_id=$2 AND import_id=$3 ORDER BY row_number""",
        row["tenant_id"],
        row["portfolio_id"],
        row["id"],
    )
    return {
        "id": row["id"],
        "client_request_id": row["client_request_id"],
        "filename": row["source_filename"],
        "status": effective_status(row),
        "row_count": row["row_count"],
        "valid_count": row["valid_count"],
        "error_count": row["error_count"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "committed_at": row["committed_at"],
        "rows": [
            {
                "row_number": item["row_number"],
                "data": decoded(item["payload"]),
                "errors": decoded(item["errors"]),
            }
            for item in rows
        ],
    }


def register_imports(app, authenticated, require_write):
    root = "/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}/transaction-imports"

    @app.post(root + "/preview", status_code=201, response_model=ImportPreviewView)
    async def preview_import(
        tenant_id: UUID,
        portfolio_id: UUID,
        body: ImportPreviewRequest,
        request: Request,
        identity=Depends(authenticated),
    ):
        digest = sha256(body.csv_text.encode()).hexdigest()
        async with transaction(
            request.app.state.pool,
            identity,
            tenant_id,
            allow_demo_market_data=request.app.state.settings.allow_demo_market_data,
        ) as (connection, user, role):
            require_write(role)
            await require_portfolio(connection, tenant_id, portfolio_id)
            previous = await connection.fetchrow(
                """SELECT * FROM saas.portfolio_transaction_imports
                   WHERE tenant_id=$1 AND portfolio_id=$2 AND client_request_id=$3""",
                tenant_id,
                portfolio_id,
                body.client_request_id,
            )
            if previous:
                if previous["content_sha256"] != digest:
                    raise HTTPException(409, "Request ID already used for different CSV content")
                return await preview_payload(connection, previous)
            rows = parse_transactions(body.csv_text, body.client_request_id)
            await validate_portfolio_state(connection, tenant_id, portfolio_id, rows)
            valid_count = sum(not item["errors"] for item in rows)
            import_id = uuid4()
            expires_at = datetime.now(UTC) + timedelta(hours=24)
            record = await connection.fetchrow(
                """INSERT INTO saas.portfolio_transaction_imports
                   (tenant_id,portfolio_id,id,client_request_id,content_sha256,source_filename,
                    row_count,valid_count,error_count,created_by,expires_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *""",
                tenant_id,
                portfolio_id,
                import_id,
                body.client_request_id,
                digest,
                body.filename,
                len(rows),
                valid_count,
                len(rows) - valid_count,
                user,
                expires_at,
            )
            await connection.executemany(
                """INSERT INTO saas.portfolio_transaction_import_rows
                   (tenant_id,portfolio_id,import_id,row_number,payload,errors)
                   VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb)""",
                [
                    (
                        tenant_id,
                        portfolio_id,
                        import_id,
                        item["row_number"],
                        json.dumps(item["data"]),
                        json.dumps(item["errors"]),
                    )
                    for item in rows
                ],
            )
            await audit(connection, tenant_id, user, "portfolio.import_previewed", import_id)
            return await preview_payload(connection, record)

    @app.post(root + "/{import_id}/commit", response_model=ImportCommitView)
    async def commit_import(
        tenant_id: UUID,
        portfolio_id: UUID,
        import_id: UUID,
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
            await require_portfolio(connection, tenant_id, portfolio_id, lock=True)
            item = await connection.fetchrow(
                """SELECT * FROM saas.portfolio_transaction_imports
                   WHERE tenant_id=$1 AND portfolio_id=$2 AND id=$3 AND created_by=$4 FOR UPDATE""",
                tenant_id,
                portfolio_id,
                import_id,
                user,
            )
            if item is None:
                raise HTTPException(404, "Import preview not found")
            if item["status"] == "committed":
                version = await connection.fetchval(
                    "SELECT version FROM saas.portfolios WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    portfolio_id,
                )
                return {
                    "import_id": import_id,
                    "status": "committed",
                    "imported_count": item["valid_count"],
                    "portfolio_version": version,
                    "committed_at": item["committed_at"],
                }
            if item["expires_at"] <= datetime.now(UTC):
                raise HTTPException(409, "Import preview expired; preview the file again")
            if item["error_count"]:
                raise HTTPException(409, "Import contains row errors and cannot be committed")
            rows = await connection.fetch(
                """SELECT row_number,payload FROM saas.portfolio_transaction_import_rows
                   WHERE tenant_id=$1 AND portfolio_id=$2 AND import_id=$3 ORDER BY row_number""",
                tenant_id,
                portfolio_id,
                import_id,
            )
            for row in rows:
                body = TransactionCreate.model_validate(decoded(row["payload"]))
                try:
                    _, created = await record_transaction(
                        connection,
                        tenant_id,
                        portfolio_id,
                        user,
                        body,
                        portfolio_locked=True,
                    )
                    if not created:
                        raise HTTPException(409, "Transaction was already recorded")
                except HTTPException as exc:
                    raise HTTPException(
                        409,
                        f"Row {row['row_number']} no longer matches the portfolio: {exc.detail}",
                    ) from None
            committed_at = datetime.now(UTC)
            await connection.execute(
                """UPDATE saas.portfolio_transaction_imports
                   SET status='committed',committed_at=$4
                   WHERE tenant_id=$1 AND portfolio_id=$2 AND id=$3""",
                tenant_id,
                portfolio_id,
                import_id,
                committed_at,
            )
            await audit(connection, tenant_id, user, "portfolio.import_committed", import_id)
            version = await connection.fetchval(
                "SELECT version FROM saas.portfolios WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                portfolio_id,
            )
            return {
                "import_id": import_id,
                "status": "committed",
                "imported_count": len(rows),
                "portfolio_version": version,
                "committed_at": committed_at,
            }

    @app.get(root, response_model=list[ImportHistoryView])
    async def list_imports(
        tenant_id: UUID,
        portfolio_id: UUID,
        request: Request,
        limit: int = Query(20, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            _,
            _,
        ):
            await require_portfolio(connection, tenant_id, portfolio_id)
            rows = await connection.fetch(
                """SELECT * FROM saas.portfolio_transaction_imports
                   WHERE tenant_id=$1 AND portfolio_id=$2 ORDER BY created_at DESC LIMIT $3""",
                tenant_id,
                portfolio_id,
                limit,
            )
            return [
                {
                    "id": row["id"],
                    "filename": row["source_filename"],
                    "status": effective_status(row),
                    "row_count": row["row_count"],
                    "valid_count": row["valid_count"],
                    "error_count": row["error_count"],
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                    "committed_at": row["committed_at"],
                }
                for row in rows
            ]
