# Daily market analysis and the local trading demo

The application now joins instrument discovery, persistent daily market history, portfolio valuations, explanatory anomaly detection, saved watchlists and alerts, a browser dashboard, and isolated paper trading. Live exchange feeds and real broker execution remain unconnected because no provider credentials or broker integration details have been supplied.

## Run the complete local demo

From an initialized repository environment:

```sh
docker compose -f docker-compose.yml -f compose.demo.yml up -d --build api
docker compose -f docker-compose.yml -f compose.demo.yml run --rm --no-deps bootstrap python scripts/seed_demo_market.py
```

Open **http://localhost:8000**. Choose Alice or Bob, create a workspace, then click **Load sample portfolio**. Inspect the instruments, save a valuation, open a paper account and submit a simulated buy or sell. All demo prices, calendars, FX and instruments are fictional; the interface labels the environment and recorded data accordingly. Demo quotes are not forecasts or trading recommendations.

The override explicitly enables the demo catalog, paper trading and development sign-in. These flags are off by default and forbidden in production. Compose binds the API and development identity issuer to loopback. The browser holds its ten-minute access token in memory; reloading/signing out clears it. The development login proxies only the configured local development issuer, never signs its own tokens, and is not a production sign-in workflow. External browser sign-in now supports [Authorization Code + PKCE](browser-sign-in.md); it requires configuring a public client at your identity provider.

The seed command imports about 120 calendar days of repeatable fictional weekday sessions/bars and 45 days of upcoming fictional sessions. Re-running it adds missing observations and preserves identical existing bars; data does not auto-refresh. Re-run it on later days to extend demo coverage. Real exchange holidays, special sessions and corporate actions are not represented by this synthetic calendar.

## 2. Persistent market data

Migration 006 adds selected instrument feeds, daily OHLCV bars, session schedules, FX observations, import provenance, and valuation snapshots. A bounded operator import ingests a normalized JSON export:

```sh
uv run python scripts/import_market_data.py path/to/export.json --validate-only
```

For ingestion, run the same script with the operator/migration database credential and a file mounted inside the container. Real exports omit `--allow-demo`. Schema fields are defined in `services/analytics/market.py`; `source`, `is_demo`, and `max_age_seconds` accompany `sessions`, `bars`, and `fx` arrays. Decimal values must be strings. Maximum payload is 8 MiB, with 10,000 bars, 10,000 sessions and 1,000 FX records. Empty/duplicate/invalid payloads, future completed bars, invalid OHLC bounds, unknown listings, and inconsistent demo provenance are rejected.

Each bar must match an imported session close. Calendar timestamps must carry UTC offsets; the adapter/operator must derive them from the authoritative exchange schedule, including Moroccan timezone/holiday changes. Import all sessions across the intended history and future evaluation window; the system cannot identify a missing calendar date that the source itself omitted. Identical payloads are deduplicated by SHA-256; conflicting bars, FX observations, calendars, selected sources or freshness budgets are rejected. Changes of provider and corporate-action restatements need a reviewed versioning workflow, rather than overwriting history. API users have read-only access to shared market data.

`GET /v1/instruments/{id}/history?limit=61` returns chronological bars (limit 1–366) from one selected source, as-of/receipt timestamps and quality. `GET /v1/instruments/{id}/quote` prefers the last stored completed bar and labels it demo/end-of-day. The importer is a provider-export adapter, not a live network feed. A concrete authorized provider adapter still needs its protocol, mapping, credentials, and redistribution permissions.

Quality checks compare the latest observation with the expected completed session, check gaps in the returned window, enforce the configured age budget, and require calendar coverage through the evaluation time. Statuses include missing, gap, stale, calendar_unknown, demo, and end_of_day. End-of-day observations do not certify current intraday conditions. Feed defaults allow up to four calendar days of age; the explicit session checks still reject missed completed sessions.

## 3. Portfolio valuation

- `GET /v1/workspaces/{tenant}/portfolios/{id}/valuation`: preview a daily-close valuation.
- `POST .../valuations`: store an immutable valuation snapshot and audit entry.
- `GET .../valuations/{snapshot_id}`: retrieve the original snapshot within the authorized workspace/portfolio.

Calculations use exact decimal arithmetic, group open holdings by listing/currency, and record price-bar and FX observation IDs. Cross-currency values require a fresh direct rate from the selected source and the same real/demo classification; no guessed, inverted, chained or cross-provider FX is substituted. Missing/stale prices or FX produce an **incomplete** result with a null total and explicit valued subtotal. Allocations are withheld until all positions are valued. Demo holdings mark the whole valuation as demo.

Valuations run in a consistent PostgreSQL transaction and reference the portfolio version. Saved payloads retain that version, inputs, method and evaluation timestamp even after later trades or reference-data changes. Snapshots prevent deleting their parent portfolio. The synchronous workflow is capped at 500 open positions. This is gross position valuation and allocation, not cost-basis/P&L/tax accounting; cash accounts, dividends, splits and other corporate-action processing remain separate work.

## 4. Explainable anomaly detector

`GET /v1/instruments/{id}/signal` evaluates `daily-robust-v1` on the last 31 completed, consistently adjusted bars. It excludes the latest return/volume from its baseline. It flags:

- A daily price move of at least 5%, or absolute modified z-score above 3.5.
- Volume at least three times its historical median (or new activity after an all-zero baseline).
- Zero volume, or volume below 20% of its median baseline.

The modified z-score uses `0.6745 × (latest return − median return) / MAD`, with a 0.001 absolute-return floor on the denominator for near-flat windows. The statistical construction follows [NIST's discussion of modified z-scores](https://itl.nist.gov/div898/handbook/eda/section3/eda35h.htm); these application thresholds and the floor are explicit engineering baselines, not exchange-calibrated investment rules. Results include model version, parameters, bar IDs and numeric evidence. A potential outlier is not proof of fraud, manipulation or future loss.

Results are **elevated**, **no_anomaly_detected**, or **insufficient_data**. Short/unadjusted history, stale prices, gaps, or uncertain calendars withhold the signal. No “safe to trade” guarantee is emitted. Current tests validate fixtures and mathematical behavior, not predictive accuracy on real markets. Production use needs licensed historical data, corporate-action review, walk-forward evaluation, false-alert analysis and exchange-specific calibration. There is no automatic order placement from a signal.

## 5. Watchlists and risk alerts

Workspace members can save up to 100 catalog instruments and enable or pause one `daily_anomaly` rule per instrument. `POST /v1/workspaces/{tenant}/risk-scans` accepts a client request UUID, evaluates enabled rules at one recorded evaluation time, and stores its status, counts, model results, requester, and timestamps. Reusing a request UUID returns the original run, including for concurrent retries.

Elevated signals create durable alerts containing the model version, parameters, reasons, numeric statistics, and source bar IDs. The deduplication key combines the rule, model version, and latest evaluated bar, so rescanning unchanged evidence does not create another alert. Members can acknowledge alerts; viewers can inspect rules, scan history, and evidence but cannot change state. Forced row-level security applies to all four tables. The synchronous scan is bounded to 100 rules. A production delivery phase still needs a worker queue, retry policy, notification outbox, and missed-delivery recovery.

See [risk-alerts.md](risk-alerts.md) for endpoints and invariants.

## 6. Next.js trading workspace

The responsive website is a Next.js 16 and React 19 application styled with Tailwind CSS 4. Its optimized static export is served by the API at `/`, keeping browser calls same-origin. The production image builds the frontend from `apps/web/package-lock.json`; `npm run build` publishes the same export locally. A restrictive Content Security Policy hashes Next's exact inline bootstrap payloads rather than allowing arbitrary inline scripts.

Before authentication the site presents the public FinRisk product, capabilities, account model, and sign-in call to action. After sign-in, a compact trading workspace provides focused Overview, Portfolio, Markets, Risk Alerts, Paper Trading, and Team views. The fixed navigation, command search, portfolio ledger, evidence panels, order ticket, dense tables, responsive mobile navigation, and shared design tokens replace the former stacked static dashboard. All existing workspace, valuation, import, alert, invitation, and paper-order API flows remain available.

Portfolio value, positions, valuation quality, and allocation lead the default workflow; research and execution remain distinct views. Chart/number formatting uses browser numbers for display only; all monetary calculations and stored values remain server-side decimals. Data is loaded on navigation or explicit Refresh; this is not a realtime streaming dashboard.

## 7. Paper trading and the live boundary

Each workspace can open one paper account per currency through `/v1/workspaces/{tenant}/paper-accounts`. Accounts start with 100,000 simulated units. `GET /{account}` returns simulated cash and positions; `GET /{account}/orders` is paginated; `POST /{account}/orders` accepts `client_request_id`, `instrument_id`, `price_bar_id`, `side` and decimal-string `quantity`.

Only demo instruments are accepted. Orders reference an explicitly viewed latest daily bar. The server checks instrument activity, currency, data freshness, sufficient simulated cash and long-only holdings. Fills are immediate at that close with zero fees/slippage, not a model of achievable live execution. Orders are terminal **filled** or **rejected**; pending orders, limits, cancel/replace and asynchronous broker reconciliation are not simulated. Account locking prevents concurrent overspending/overselling. Retrying the same request ID returns the prior result; changing its payload returns 409. A changed/missing reference price requires refresh. Cash, order history and audit writes commit together. Paper fills never enter the real/manual portfolio ledger.

Paper account/order records use forced tenant RLS. Viewers may read but cannot submit. Live orders return 501 through the explicit `/v1/workspaces/{tenant}/live-orders` boundary. No broker is called, no real funds are moved, and no external trade authorization is inferred. Finishing live execution requires a selected broker's sandbox, authentication, supported instruments/order types, pre-trade controls, and reconciliation design.

## Verification commands

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not integration"
cd apps/web && npm ci && npm run typecheck && npm run build && cd ../..
docker compose -f docker-compose.yml -f compose.test.yml build
docker compose -f docker-compose.yml -f compose.test.yml run --rm tests
uv run --with playwright python scripts/smoke_dashboard.py
```

If Chromium is missing, install it with `uv run --with playwright playwright install chromium`. The browser smoke test expects the running seeded demo, creates a dedicated workspace, validates valuation/anomaly/paper buy/sell flows, checks mobile overflow and captures screenshots in `.artifacts/`. It retains its demo records for inspection.

Verified on 2026-10-02: the rebuilt production image and full containerized backend suite passed 200 tests, including PostgreSQL/Kafka integration, static frontend security, team invitations, atomic portfolio CSV imports, concurrent risk-scan idempotency, alert deduplication, and tenant role enforcement. The Next.js production export passed TypeScript checking and the Microsoft Edge browser smoke for login, workspace creation, sample holdings, valuation, risk alert creation and acknowledgment, simulated buys/sells, logout, and mobile overflow. PostgreSQL and Kafka reported healthy during this verification run.
