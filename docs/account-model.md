# User accounts and workspace access

FinRisk is account based. Production registration and sign-in are delegated to the configured OpenID Connect identity provider using Authorization Code with PKCE. FinRisk does not store user passwords.

After the provider verifies a person, the API validates the signed issuer and subject claims and creates the corresponding FinRisk user record on first authenticated access. The `(issuer, subject)` pair is unique, so separate registered identities never collapse into the same account. Disabled accounts receive `403` before workspace data is opened.

Accounts without a workspace receive a dedicated first-run screen. Creating the initial workspace and portfolio uses one database transaction, so an interrupted request cannot leave a half-configured account. A first-run account can instead accept an invitation and join an existing workspace. The onboarding endpoint rejects repeat use after any workspace membership exists.

An account may own or join multiple workspaces. Every portfolio, transaction import, valuation, watchlist, alert, paper account, and audit event belongs to a workspace. Membership roles are `owner`, `admin`, `member`, and `viewer`. PostgreSQL forced row-level security checks the authenticated user and active workspace on each request, including read paths.

The local demo exposes Alice and Bob through the development identity service. They are separate accounts and cannot read one another's private workspaces. This selector is disabled in production. Public deployment requires configuring a provider that supports the desired registration policy, verified email rules, MFA, account recovery, and abuse controls.

See [browser-sign-in.md](browser-sign-in.md) for the OIDC flow and deployment configuration, and [team-workspaces.md](team-workspaces.md) for invitations and roles.
