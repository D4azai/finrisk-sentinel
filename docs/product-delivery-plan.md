# SaaS delivery plan

This plan tracks the work between the current local vertical slice and a paid production service. A feature is complete only when its tenant isolation, audit trail, failure behavior, UI state, and operational path are verified.

## Current baseline

The repository has authenticated workspaces, team invitation and role management, a verified instrument catalog, an append-only portfolio ledger with bounded preview-and-commit CSV imports, daily bars and FX imports, exact-decimal valuation snapshots, portfolio tail-risk and position-attribution analysis with reproducible evidence snapshots, persistent watchlists and explainable risk alerts, paper trading, and a responsive Next.js/Tailwind trading workspace. Kafka and PostgreSQL provide durable market ingestion and replay. Live equity data, payment processing, transactional email, and broker execution are still provider-dependent boundaries.

## Execution order

| Order | Product slice | Completion gate |
|---:|---|---|
| 1 | Team onboarding — delivered | Expiring one-time invites, role changes, revocation, removal, audit, and tenant tests |
| 2 | Portfolio import — delivered | Preview/validate CSV, idempotent commit, per-row errors, import history, and large-file job boundary |
| 3 | Risk scans and in-app alerts — foundation delivered | Saved rules, bounded idempotent scans, durable evidence, alert deduplication, history, acknowledgment, tenant policy, then asynchronous workers and delivery outbox |
| 4 | Portfolio Risk Lab — first method delivered | Historical VaR and Expected Shortfall, volatility, drawdown, concentration, diversification, position risk attribution, deterministic stress tests, data-quality limits, fingerprints, saved evidence, RLS, and tenant tests |
| 5 | Entitlements and billing — foundation delivered | Versioned plans, workspace subscriptions, concurrent server-side quotas, provider mapping fields, durable webhook inbox, and usage UI are delivered; add provider signature verification, event processing/replay, reconciliation, checkout, grace/cancel transitions, and billing portal after provider selection |
| 6 | External identity and email | Production OIDC tenant, account profile policy, verified sender, invitation/reset templates, bounce handling, and key rotation drill |
| 7 | Licensed market integrations | Provider adapters for Casablanca and target international venues, calendars, corporate actions, FX provenance, backfill, and completeness checks |
| 8 | Professional web application — foundation delivered | Next.js/TypeScript component shell, Tailwind design system, accessible navigation/forms/tables, responsive charts, production export, and browser automation; add frontend telemetry and richer loading skeletons before public launch |
| 9 | Broker sandbox | Explicit order state machine, pre-trade checks, idempotency, webhook/poll reconciliation, kill switch, and paper/live visual separation |
| 10 | Production operations | Infrastructure as code, secrets, TLS/ACL verification, backups and restore drill, metrics/alerts, SLOs, load tests, retention/cost model, and staged rollout |

Provider work begins with commercial and regulatory decisions: launch countries, supported exchanges, redistribution rights, expected users/events, billing entity, broker eligibility, and budget. Adapters remain behind the existing provider boundaries so demo and test fixtures never masquerade as live data.
The current official-source findings and required choices are in the [provider integration brief](provider-integration-decisions.md).

## Language boundaries

Use TypeScript for the rebuilt web client, Python for product APIs/workers and model orchestration, SQL for durable invariants and tenant isolation, and language-neutral schemas for every service boundary.

C++ is a phase-six optimization, not a prerequisite for the SaaS. Candidate kernels are rolling robust statistics, large covariance/stress calculations, Monte Carlo workloads, and batch portfolio aggregation. A kernel moves to C++ only after a representative benchmark identifies it as a material CPU bottleneck. The native boundary must have a versioned Protobuf/gRPC contract, bounded batches and deadlines, documented numeric precision/overflow rules, cancellation, golden datasets, differential Python/C++ tests, sanitizers, and regression benchmarks. Exact monetary records stay decimal outside floating-point kernels.

Rust or Go should be considered only if measured connection fan-out, provider protocol handling, or isolated service deployment warrants another runtime. Authentication, billing, permissions, audit, and workflow coordination remain in the application layer.

## Immediate next slice

Add licensed price, corporate-action, benchmark, and historical FX coverage. That unlocks benchmark-relative performance, currency-aware historical risk, user-defined stress shocks, and portfolio optimization without overstating demo evidence. In parallel, move bounded scans into a durable worker and settle billing, email, and broker providers.
