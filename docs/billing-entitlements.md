# Billing and entitlements

FinRisk bills and limits access at the workspace boundary. Plan versions are internal product records and remain independent of payment-provider price identifiers. Every workspace receives an active `free` subscription when it is created, including workspaces created during first-run onboarding. Migration 011 backfills existing workspaces.

The initial free plan permits 5 seats, 10 portfolios, 25 watchlist instruments, and 100 risk scans per calendar month. These are early-access limits rather than published commercial terms. Paid tiers and prices must be added only after the legal billing country, merchant account, currency, tax treatment, and payment provider are selected.

The API exposes:

- `GET /v1/plans` for active versioned plans.
- `GET /v1/workspaces/{workspace_id}/subscription` for the current plan, lifecycle state, entitlements, and usage.

Portfolio, seat, watchlist, and monthly risk-scan limits are checked in PostgreSQL under a subscription-row lock. This makes the decision safe when concurrent requests race at the limit. Invitation acceptance checks the seat limit inside the same security-definer function that consumes the invitation.

The schema includes provider customer/subscription mappings, lifecycle states, an append-only billing audit, and a deduplicated webhook inbox that retains the raw signed payload boundary. The webhook HTTP route and processor remain disabled until a provider is selected and its signature contract is available. Browser redirects will never grant entitlements; verified provider events and reconciliation will update the subscription projection.
