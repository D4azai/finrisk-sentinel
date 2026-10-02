# Browser sign-in with an external identity provider

FinRisk supports a public OpenID Connect client using Authorization Code with PKCE S256. The dashboard redirects users to the configured provider, validates the one-use browser transaction, and exchanges the code through the API. The API verifies both the ID token and the access token before returning an in-memory browser session. This implementation is available but no external provider is connected by default.

## Configure a provider

Register a **public client** (no client secret) with Authorization Code and mandatory PKCE S256. Register the exact application callback, for example `https://finrisk.example/auth/callback`. Configure the provider to issue RS256-signed JWT access tokens for the existing `API_OIDC_AUDIENCE`, with the existing `API_REQUIRED_SCOPE` (default `finrisk:access`), and ID tokens for the browser client. Both tokens must identify the same issuer and subject. Opaque access tokens and providers requiring confidential-client credentials are not supported by this integration.

The API validates the token's issued-at and expiry timestamps. Production hosts and developer machines must synchronize their clocks through the operating system's time service. If every issuer, audience, signature algorithm, and scope check matches but a newly issued token is rejected, compare the host and container UTC time with a trusted network clock before changing token validation policy.

Set these deployment variables together:

```dotenv
API_ENABLE_DEV_LOGIN=false
API_BROWSER_CLIENT_ID=your-public-client-id
API_BROWSER_AUTHORIZATION_URL=https://identity.example/authorize
API_BROWSER_TOKEN_URL=https://identity.example/token
API_BROWSER_REDIRECT_URI=https://finrisk.example/auth/callback
API_OIDC_ISSUER=https://identity.example
API_OIDC_JWKS_URL=https://identity.example/jwks
API_OIDC_AUDIENCE=finrisk-api
API_REQUIRED_SCOPE=finrisk:access
```

Use the actual issuer and endpoints supplied by your provider; the URLs above are placeholders. If your provider requires an `audience` parameter on its authorization request, set `API_BROWSER_AUTH_AUDIENCE`. FinRisk requests `openid` plus the API access scope. It does not request offline access or retain refresh tokens. No provider discovery or arbitrary endpoint from a browser request is accepted.

Serve the application at the configured callback origin. Authorization, token and callback URLs require HTTPS; explicit test/development mode allows HTTP only on loopback hosts. Production also requires the existing verified database TLS configuration and disables all demo features. The standard Compose file is a development deployment; `compose.demo.yml` explicitly enables demo login and must not be combined with external browser-login configuration. The existing identity verifier accepts RS256 only, including for ID tokens.

## Session behavior

The sign-in transaction stores random state, nonce, PKCE verifier, creation time and configuration binding in tab-scoped session storage. It expires after ten minutes and is removed before the exchange. A mismatched, repeated, expired or cancelled callback cannot establish a session. The callback is removed from the browser address before API requests. The application suppresses callback query parameters in its ASGI scope so the built-in access log does not retain authorization codes; configure any reverse proxy, CDN and external request logging to omit callback queries and token-exchange bodies too.

`POST /v1/auth/exchange` accepts only `code`, `code_verifier` and `nonce`, requires the configured application Origin, uses the pinned token endpoint without redirects, and bounds the response size/time. Verification checks signatures, issuer, audiences, timestamps, API scope, nonce, authorized party for multiple ID-token audiences, optional access-token hash and matching subjects. Invalid responses never return tokens to the browser. The identity provider must enforce one-use codes and S256 verification for this public client.

The access token remains in page memory; reload and local sign-out clear it, and expiration closes the page session. Sign-out does not revoke an already issued access token, sign out other tabs or end the provider's session. A later sign-in may reuse the provider's SSO session. Refresh, provider-wide logout, token revocation and persistent sessions are not included. An interrupted exchange requires starting a new login; the app never retries a consumed authorization code automatically.

The flow follows [OAuth security best current practice](https://www.rfc-editor.org/rfc/rfc9700.html) and [OIDC ID-token validation](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation). The state, nonce and PKCE checks bind the redirect to the initiating browser and provider. This does not replace provider configuration or a deployment review.

## Verify

```sh
uv run pytest -q tests/test_browser_auth.py tests/test_api_auth.py
uv run --with playwright python scripts/smoke_browser_login.py
```

The backend tests use a local test provider and signed tokens. The browser smoke exercises the real dashboard assets with intercepted provider/API responses, checks PKCE, state, expiry, cancellation, retry prevention, memory-only credentials and local logout. Neither test connects to an external account. Validate the configured provider's actual login, permissions and logout expectations in its staging tenant before enabling public access.
