# Portfolio transactions and holdings

FinRisk Sentinel's product direction is anomaly detection and explainable trading-risk signals for the Moroccan and international stock markets, with broker-backed trading inside the application in a later milestone. Signals should expose evidence, data freshness, and uncertainty; they must not imply guaranteed safety. The existing Binance collector remains the implemented data feed. Equity market feeds, anomaly models, and broker execution are not implemented by this milestone.

## Record completed trades

Apply migrations through the existing bootstrap service before starting the updated API:

```sh
docker compose up -d --build api
```

The authenticated portfolio routes now include:

| Method | Portfolio-relative path | Behavior |
|---|---|---|
| POST | `/transactions` | Record a completed buy or sell; 201 on creation, 200 on an identical retry |
| GET | `/transactions` | UUID-ordered ledger, with `cursor` and `limit` (1–100) |
| GET | `/holdings` | Exchange/ticker/currency aggregates, including closed positions; instrument cursor and limit |

The prefix is `/v1/workspaces/{tenant_id}/portfolios/{portfolio_id}`. Owners, admins, and members can record trades. Viewers can read them. Forced PostgreSQL row-level security isolates both reads and inserts, and the API database role cannot update or delete ledger records.

Example manual record (illustrative ticker, not a market-data lookup):

```json
{
  "client_request_id": "d84c01e5-75a9-4fe9-9ff8-26dab12002d7",
  "market": "XCAS",
  "symbol": "TEST",
  "currency": "MAD",
  "side": "buy",
  "quantity": "10.25",
  "price": "100.10",
  "fees": "2.50",
  "executed_at": "2026-01-01T12:00:00Z"
}
```

`market` is a four-character exchange identifier; symbols are qualified by their market so identical tickers on different exchanges remain separate. Since migration 005, new trades must match an imported [instrument catalog](instrument-catalog.md) listing by exchange, ticker and currency. The illustrative `TEST` ticker above requires a corresponding operator-imported listing; it is not seeded by default. Unknown listings return 409. Existing unmatched history remains readable. MAD, USD, EUR, and other three-letter currencies are supported. A market/ticker's currency cannot change within a portfolio's ledger.

Quantities, unit prices, and fees use decimal strings with up to 18 integer and 12 fractional digits. Quantity and price must be positive; fees default to zero and are denominated in the transaction currency. Execution times must include a timezone and cannot be in the future. Records must arrive in nondecreasing execution-time order for each market/ticker. Equal timestamps are accepted in recording order. Backdated insertion returns 409. This long-only milestone rejects sales exceeding recorded holdings; it does not check a cash account or reserve funds.

Reuse a `client_request_id` only for retries of the same trade within the same portfolio. Reusing it with different trade fields returns 409. Retry comparison uses parsed decimal values and UTC timestamps. A portfolio row lock serializes writes, so duplicate requests and concurrent sales cannot double-count through these API routes. Successful new trades increment portfolio version and append an audit event atomically. Rejected writes and retries do neither. Database privileges enforce isolation and immutability; chronological and inventory validation lives in the API.

Holdings return exact quantity, total fees, last execution time, and `net_cash_flow`: sale proceeds minus buy expenditure minus all fees, in each instrument's currency. Cash flow is not profit, cost basis, valuation, or a cash balance. Currencies are never summed together. Quantities remain derived from the immutable ledger. Pagination is live, not a frozen snapshot; restart pagination to capture concurrent inserts that sort before a cursor.

Portfolios with transaction history return 409 on deletion, even after all positions are closed. Corrections/reversals, corporate actions, transfers, dividends, FX valuation, CSV imports, short selling, and broker reconciliation need subsequent workflows. Recorded trades are manual historical entries; these endpoints never submit orders to a broker.

## Next milestones

1. Instrument directory and licensed equity feeds for Morocco and selected international venues, with exchange calendars, freshness, and completeness checks.
2. Corrections/imports and corporate actions, then portfolio valuation and allocation with explicit FX provenance.
3. Defined, evaluated anomaly detectors and explainable risk signals, including an unknown/insufficient-data state, surfaced in a dashboard.
4. Broker integration with order lifecycle, authorization, pre-trade controls, fills, and reconciliation.

## Verification

Verified 2026-09-30: lint and formatting pass, 75 local unit tests pass, and the complete Docker suite passes all 100 tests (including 25 PostgreSQL/Kafka integration tests). Ledger coverage includes decimal products beyond 28 digits, identical/conflicting retries, concurrent duplicate buys and competing sells over multiple database connections, tenant isolation, viewer restrictions, database immutability, pagination, exchange separation, and rollback when audit insertion fails. Migration 004 also applied successfully through local bootstrap. The Kafka health-check timeout is now 30 seconds because its Java CLI exceeded the previous ten-second timeout on the development machine.
