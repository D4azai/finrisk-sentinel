# Multi-user API foundation

For the subsequent valuation, anomaly, dashboard and paper-trading endpoints, see the [current application workflow](application-workflow.md). This document records the original identity/workspace foundation.

Implemented 2026-09-28. This milestone adds authenticated identities, workspaces, memberships, and isolated portfolio metadata. The subsequent [portfolio ledger](portfolio-ledger.md) adds manual transactions and holdings. CSV imports, valuations, dashboard UI, subscriptions, and team invitations remain subsequent milestones.

## Try it locally

For the existing repository environment:

```sh
uv sync --locked
uv run python scripts/init_api_env.py
docker compose up -d --build api
uv run python scripts/smoke_api.py
```

For a fresh clone, `scripts/init_local_env.py` initializes both pipeline and API settings. Initializers preserve existing modern credentials. The API is at http://localhost:8000, interactive documentation at http://localhost:8000/docs, and the development issuer at http://localhost:8081. Both published listeners bind only to host loopback. Database/Kafka ports remain private.

POST `{"user":"alice"}` or `{"user":"bob"}` to `http://localhost:8081/token` to obtain a ten-minute development access token. Use `Authorization: Bearer <access_token>` on API requests. The development issuer intentionally has no passwords and is only suitable for these local sample identities. It requires explicit development enablement, is a separate service, and has no database credentials. Its private RSA key is generated in memory; restart it and obtain fresh tokens. The application API never signs tokens or stores passwords.

The smoke script does not print tokens. It creates separate demo workspaces, exercises portfolio creation/read/delete, verifies cross-tenant denial, and retains workspaces/audit history for inspection.

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| GET | `/v1/me` | Resolve/provision the authenticated identity and return its internal user ID |
| POST | `/v1/workspaces` | Create a workspace and its owner membership atomically |
| GET | `/v1/workspaces` | List only the caller's memberships/workspaces; UUID cursor pagination |
| GET | `/v1/workspaces/{tenant_id}` | Get a workspace the caller belongs to |
| POST | `/v1/workspaces/{tenant_id}/portfolios` | Create named portfolio metadata with base currency |
| GET | `/v1/workspaces/{tenant_id}/portfolios` | Paginated list confined to that workspace |
| GET | `/v1/workspaces/{tenant_id}/portfolios/{id}` | Read one authorized portfolio |
| PATCH | `/v1/workspaces/{tenant_id}/portfolios/{id}` | Rename with `{ "name": "New name", "version": 1 }`; stale versions return 409 |
| DELETE | `/v1/workspaces/{tenant_id}/portfolios/{id}` | Owner/admin deletion with an audit entry |

Owners/admins can create, read, rename and delete portfolios. Members can create, read and rename. Viewers can only read. Membership management/invitations are not public endpoints yet; tests seed team roles through the migration principal. A personal account uses an ordinary workspace with an owner membership, so the data model can support teams later.

Unauthenticated/invalid tokens return 401, insufficient role privileges 403, and inaccessible or missing workspaces/portfolios 404. Requests cannot assign `tenant_id`, `created_by`, or roles through extra JSON fields. Bodies are capped at 16 KiB with a ten-second read deadline; list sizes are capped at 100. Responses disable caching and include a generated request ID. API documentation exposes schemas, not private records.

## Authentication and production configuration

The API validates RS256 signatures from a configured JWKS URL, exact issuer, API audience, expiration, issued-at and optional not-before time, a nonempty subject, and the `finrisk:access` scope. User identity is `(issuer, subject)`, not email. Token-supplied key URLs are never fetched, and token-supplied algorithms cannot broaden the allowlist. JWKS retrieval is asynchronous, bounded, cached, and refresh-throttled; provider failure after cache expiry fails closed. Invalid signatures/claims never provision a user.

Production needs an actual OIDC/OAuth provider. The dashboard supports [browser Authorization Code + PKCE sign-in](browser-sign-in.md), including public-client configuration and callback validation. Configure the API verifier:

- `API_ENVIRONMENT=production`
- `API_DATABASE_URL`: restricted login with `sslmode=verify-full`
- `API_OIDC_ISSUER`: exact HTTPS issuer from the provider
- `API_OIDC_JWKS_URL`: administrator-configured HTTPS key endpoint
- `API_OIDC_AUDIENCE`: API resource identifier, separate from a browser client ID
- `API_REQUIRED_SCOPE=finrisk:access` (or the provider's explicitly configured API scope)

The production provider must issue access tokens for this audience/scope; do not configure the API to accept browser ID tokens. Do not deploy `dev_identity`, use the local plaintext Compose setup publicly, or pass migration/database-admin secrets to the API. Production needs TLS ingress, distributed rate limiting, secret management, identity-provider operations, and hosting-specific rollout checks. The current API is a tested foundation, not a complete production onboarding product.

## Database isolation

Migration 003 creates the `saas` schema and five tables: users, workspaces, memberships, portfolios, audit_events. User and tenant IDs use UUIDs; portfolio primary keys include tenant ID. Row-level security is enabled and forced on every table. Runtime identity and workspace context use transaction-local PostgreSQL settings, which disappear on commit or rollback; connections are pooled and never retain authorization decisions.

The local API login is separate from the pipeline/migration login and inherits only `finrisk_api`. It cannot own tables, bypass RLS, change memberships, modify account activation, access pipeline tables, or acquire the privileged bootstrap role. Startup rejects roles with bypass/ownership privileges or membership paths to privileged roles. The API container receives its own connection URL, not the pipeline/admin environment file.

One narrow SECURITY DEFINER function creates a workspace and its initial owner membership. It is owned by the NOLOGIN `finrisk_workspace_bootstrap` role, which intentionally has BYPASSRLS but only the table permissions needed for this operation. PUBLIC execute is revoked; the function has a fixed search path, accepts only a workspace name, verifies the active actor against the authenticated identity context, and has no dynamic SQL. No runtime login is a member of that role. Provisioning these roles requires a privileged migration principal; production operators must explicitly approve/provision that role model in their database platform.

All other database access uses forced RLS and normal runtime privileges. Policies and HTTP handlers both enforce current membership; roles are not trusted from JWT claims. Account disabling and membership removal apply on the next request. In-flight transactions may complete during administrative revocation. Audit records commit with successful mutations and are append-only to the API role. There are no cross-tenant jobs, downloads, or realtime endpoints in this milestone; those future paths must adopt the same authorization model.

## Verification and remaining work

The suite includes genuine RSA signature/JWKS tests and PostgreSQL/HTTP tests with the restricted login, including two-user read/write/delete isolation, unfiltered SQL isolation, direct cross-tenant insert denial, pool reuse after rollback, read-only roles, revocation, disabled users, concurrent rename conflicts, audit counts, and invalid-token rejection. Integration tests use disposable isolated databases; they do not truncate application data.

Windows Time was stopped during verification. Starting the service/resynchronizing was denied by the current Windows session. A machine administrator should enable time synchronization and run `w32tm /resync`, then check actual exchange/container drift. The market-data future-timestamp limit remains intact. Local identity issuance and API verification use the same container-host clock; this does not certify production provider clock synchronization.

Portfolio transactions and holdings are now described in the [ledger milestone](portfolio-ledger.md), including migration 004 and history-preserving deletion behavior. Next: equity instrument/feed integration, valuation/allocation, and evaluated anomaly signals for Moroccan and international markets. Team invitations, billing entitlements, import processing, and broker order execution remain later work.
