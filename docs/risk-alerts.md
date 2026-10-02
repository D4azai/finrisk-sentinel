# Watchlists and explainable risk alerts

Migration 010 adds workspace watchlists, daily-anomaly rules, recorded scan runs, and durable alerts. Every table uses forced row-level security. Owners, admins, and members may change rules, run scans, and acknowledge alerts; viewers have read access only.

## API flow

1. `POST /v1/workspaces/{tenant}/watchlist` saves a catalog `instrument_id` and creates its daily rule. The workspace limit is 100 instruments.
2. `PATCH /v1/workspaces/{tenant}/watchlist/{instrument_id}` enables or pauses the rule. Deleting the watchlist item also deletes its rule.
3. `POST /v1/workspaces/{tenant}/risk-scans` takes `client_request_id`. The ID is an idempotency key within the workspace.
4. `GET /v1/workspaces/{tenant}/risk-scans` returns recent durable run status and counts.
5. `GET /v1/workspaces/{tenant}/alerts` accepts optional `status=open` or `status=acknowledged` and a bounded limit.
6. `POST /v1/workspaces/{tenant}/alerts/{alert_id}/acknowledge` records the actor and time.

The scan evaluates at most 100 enabled rules in a repeatable-read transaction. It stores each result even when no anomaly is found. An elevated result creates an alert with the complete `daily-robust-v1` evidence: model parameters, reasons, z-scores, medians, latest values, quality metadata, and exact input bar IDs.

Alerts deduplicate on the rule ID, model version, and latest input bar. Repeating a scan over unchanged observations can produce an elevated scan result while `new_alert_count` stays zero. New market evidence can create a new alert. Acknowledgment changes workflow status only; it never changes or removes the recorded evidence.

This release deliberately bounds evaluation inside the request so the product loop is functional without implying asynchronous reliability. The production follow-up is to claim persisted jobs in a worker, add leases/heartbeats and retry limits, and write notification intents to a transactional outbox. Email, push, or webhook delivery must consume that outbox idempotently and retain delivery history.
