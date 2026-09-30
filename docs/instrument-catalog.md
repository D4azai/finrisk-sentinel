# Step 1: equity instrument catalog and provider boundary

Subsequent implementation: stored daily-history imports, calendars, FX, valuations, anomaly checks, the dashboard and paper trading are now available. See the [application workflow](application-workflow.md) for the current end-to-end setup; the original step-1 preview provider described below remains a fallback when no stored history exists.

The catalog is implemented; a live equity feed is not connected. There is no default real-security seed and no automatic website scraping. Operators import reviewed reference data, and the application exposes authenticated, read-only discovery. The optional sample catalog contains explicitly fictional equities.

## API

| Method | Route | Result |
|---|---|---|
| GET | `/v1/instruments` | Search by `q` (name/ticker/ISIN), `market`, `currency`, `active`; UUID `cursor`, `limit` 1–100 |
| GET | `/v1/instruments/{id}` | Stable listing ID, exchange, ticker, currency, ISIN, name, status, source and verification timestamp |
| GET | `/v1/instruments/{id}/quote` | Explicit availability/quality state and an optional exact-decimal quote |
| GET | `/v1/market-data/providers` | Currently configured provider capabilities |

All routes require an active authenticated account. Instrument reference data is shared across workspaces; portfolio data remains tenant-isolated. Catalog writes are not exposed through the API. The API database role has SELECT only, with forced RLS and transaction-local identity/demo context.

A listing is keyed by `(market, symbol, currency)` and has a stable UUID. The same ISIN may appear on multiple listings. ISIN syntax and check digit are validated according to the modulus-10 method described by [ANNA](https://anna-web.org/identifiers/); passing that check does not prove that an identifier has been assigned or that metadata is correct. Operators must review the provider's instrument reference data. Only equity instruments are currently accepted. Markets and currencies are syntax-validated; authoritative exchange/currency directories and exchange calendars remain step 2 work.

## Import reference data

Migration 005 creates the catalog and import provenance tables, adds optional listing IDs to historical transactions, and applies a restrictive insert policy requiring catalog references for new application database writes. Existing ledger records are preserved without backfilling or rewriting them.

Validate a JSON file without database credentials:

```sh
uv run python scripts/import_instruments.py scripts/data/instruments.demo.json --validate-only
```

An import contains `schema_version: 1` and an `instruments` array. See the sample file for its shape. Real entries require a checksum-valid `isin` and `is_demo: false`; every entry requires `source` and a timezone-aware, nonfuture `verified_at`.

After rebuilding and applying migrations, a database operator imports with the migration credential, never the API credential:

```sh
docker compose up -d --build api
docker compose run --rm --no-deps bootstrap python scripts/import_instruments.py scripts/data/instruments.demo.json --allow-demo
```

For a real catalog, use the same script with a reviewed JSON file mounted inside the operator container and omit `--allow-demo`. Do not put credentials in the catalog. The importer reads at most 8 MiB / 10,000 entries, validates the complete payload before writing, serializes imports, and commits all records plus an import SHA-256/count atomically. Reimporting preserves listing UUIDs. Older verification timestamps, duplicate listing keys, changes of ISIN, and changes between demo and real classification are rejected. Missing rows are not deleted. Set `active: false` explicitly to mark a listing inactive. Symbol reuse, security-identity changes and corporate-action histories need a later lifecycle workflow.

The migration does not seed real securities. A newly migrated catalog is empty until an operator imports reference data. New trades for unknown exchange/ticker/currency combinations return 409; new known trades save their listing UUID and demo provenance. Inactive listings remain available for recording completed historical trades: `active` is not an execution permission. Holdings include matching catalog metadata, or `catalog_status: unregistered` when there is no accessible match. Old idempotent retries still return the original record even if no listing is registered. Demo provenance remains on recorded transactions and holdings even if demo catalog access is subsequently disabled.

## Local demo

The sample catalog uses `DEMO-MA` in MAD and `DEMO-US` in USD, with clearly fictional names and no fabricated ISINs. It is never imported automatically. Both the importer and quote provider reject demo enablement in production.

To expose imported demo instruments locally, set `API_ALLOW_DEMO_MARKET_DATA=true` in your local `.env`, then recreate the API:

```sh
docker compose up -d api
```

The default is false. With demo enabled, the provider returns a fixed synthetic price of `100.00`, dated January 1, 2026, only for demo listings. It never supplies synthetic prices for real catalog entries. Responses explicitly say `status: demo`, `mode: demo`, and include their source and timestamps. This fixture exists to exercise the application plumbing; it cannot validate a financial model or power actual trades.

## Provider contract and the next step

The Python `QuoteProvider` boundary declares markets, delivery mode and history capability. Quote fields include instrument UUID, currency, decimal price, provider, as-of and receipt times, delivery mode, and session status. Calls have a bounded timeout. Wrong instruments/currencies/providers, inconsistent delivery modes, and future timestamps are rejected. Adapter transport errors return a generic unavailable state, without exposing upstream credentials. Adapters should translate transport/authentication failures to `ProviderUnavailable`.

The current provider registry contains only the opt-in demo provider. Real listings return `not_configured` or `missing`; the application does not claim market coverage merely because a catalog entry exists. Other contract states include stale, delayed, end-of-day, unknown session, closed market, invalid, unavailable, and available. Even `available` describes quote quality only; it is not a safe-to-trade signal. Provider-supplied sessions are not yet cross-checked against an authoritative calendar. Quotes are preview responses, not a persisted/reproducible valuation snapshot. History access is not implemented and the demo provider declares `supports_history: false`.

Step 2 needs an actual provider contract/account, its documented API/feed schema, instrument mapping, allowed usage, update cadence, and historical coverage. Bourse de Casablanca advertises official reference, historical and real-time services in its [market-data offer](https://www.casablanca-bourse.com/en/market-data/offre-market-data), and lists [data vendors](https://www.casablanca-bourse.com/en/market-data/rediffuseurs). Those offers do not establish that this application already has API access. Credentials belong in local secrets/configuration, never chat or committed files.

Next implementation work is a concrete authorized feed adapter, durable price/history ingestion, exchange-session/calendar handling, and freshness/completeness validation. Portfolio valuation, evaluated anomaly detectors, dashboard, and broker execution follow those data foundations in order.

## Verification

Verified 2026-09-30: all 134 tests pass in Docker, including 30 PostgreSQL/Kafka integration tests. The 104 local unit tests and lint/format checks also pass. Coverage includes ISIN check digits, invalid/duplicate/oversize imports, stable listing IDs, atomic import rollback, stale import rejection, authenticated search and pagination, catalog write denial, unknown-listing rejection, matching foreign keys, preserved legacy retries, demo enablement and retained provenance, and quote identity/freshness/timeout behavior. Migration 005 applied through the local bootstrap process without rewriting ledger history.
