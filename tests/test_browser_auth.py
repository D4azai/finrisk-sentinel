import base64
import hashlib
import time

import aiohttp
import httpx
import jwt
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from pydantic import ValidationError

from services.api.auth import TokenVerifier
from services.api.settings import APISettings
from services.api.web import CallbackPrivacy, register_web

NONCE = "n" * 43
ORIGIN = "https://finrisk.example"
BODY = {"code": "one-use-code", "code_verifier": "v" * 43, "nonce": NONCE}


def config(**overrides):
    return APISettings(
        **{
            "_env_file": None,
            "_env_prefix": "UNIT_BROWSER_",
            "environment": "test",
            "allow_insecure_local": True,
            "database_url": "postgresql://test:test@localhost/test",
            "oidc_issuer": "https://issuer.example",
            "oidc_jwks_url": "https://issuer.example/jwks",
            "browser_client_id": "finrisk-browser",
            "browser_authorization_url": "https://issuer.example/authorize",
            "browser_token_url": "https://issuer.example/token",
            "browser_redirect_uri": ORIGIN + "/auth/callback",
            **overrides,
        }
    )


@pytest.fixture
async def login_server():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    common = {"iss": "https://issuer.example", "sub": "alice", "iat": now, "exp": now + 300}

    def sign(claims):
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "first"})

    access_claims = {**common, "aud": "finrisk-api", "scope": "finrisk:access"}
    access = sign(access_claims)
    id_claims = {**common, "aud": "finrisk-browser", "nonce": NONCE}
    response = {
        "access_token": access,
        "id_token": sign(id_claims),
        "token_type": "Bearer",
        "refresh_token": "must-never-be-returned",
    }
    requests = []
    provider = {"status": 200, "response": response}

    async def token(request):
        requests.append(dict(await request.post()))
        return web.json_response(provider["response"], status=provider["status"])

    upstream = web.Application()
    upstream.router.add_post("/token", token)
    async with TestServer(upstream) as server, aiohttp.ClientSession() as session:
        settings = config(browser_token_url=str(server.make_url("/token")))
        verifier = TokenVerifier(settings, session)
        verifier.keys = {"first": key.public_key()}
        verifier.expires = time.monotonic() + 300
        app = FastAPI()
        app.state.settings = settings
        app.state.verifier = verifier
        app.state.http = session
        register_web(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as client:
            yield client, provider, requests, sign, id_claims, access_claims, settings


async def test_successful_exchange_and_public_configuration(login_server):
    client, provider, requests, *_, settings = login_server
    response = await client.post("/v1/auth/exchange", json=BODY)
    assert response.status_code == 200
    assert response.json()["access_token"] == provider["response"]["access_token"]
    assert 0 < response.json()["expires_in"] <= 300
    assert set(response.json()) == {"access_token", "expires_in"}
    assert requests == [
        {
            "grant_type": "authorization_code",
            "client_id": settings.browser_client_id,
            "redirect_uri": settings.browser_redirect_uri,
            "code": BODY["code"],
            "code_verifier": BODY["code_verifier"],
        }
    ]
    public = (await client.get("/v1/app-config")).json()["browser_login"]
    assert public["scope"] == "openid finrisk:access"
    assert "token_url" not in public
    callback = await client.get("/auth/callback?code=private&state=private")
    assert callback.status_code == 200
    assert callback.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in callback.headers["content-security-policy"]


@pytest.mark.parametrize("origin", ["https://evil.example", "null", ""])
async def test_exchange_rejects_other_origins_before_contacting_provider(login_server, origin):
    client, _, requests, *_ = login_server
    assert (
        await client.post("/v1/auth/exchange", json=BODY, headers={"Origin": origin})
    ).status_code == 403
    assert not requests


@pytest.mark.parametrize(
    "changes",
    [
        {"nonce": "wrong"},
        {"sub": "bob"},
        {"aud": "other-client"},
        {"iss": "https://other.example"},
        {"exp": 1},
        {"iat": True},
        {"iat": []},
        {"exp": {}},
        {"azp": "other-client"},
        {"aud": ["finrisk-browser", "other-client"]},
        {"at_hash": "wrong"},
    ],
)
async def test_invalid_id_token_cannot_establish_session(login_server, changes):
    client, provider, _, sign, claims, *_ = login_server
    provider["response"]["id_token"] = sign({**claims, **changes})
    response = await client.post("/v1/auth/exchange", json=BODY)
    assert response.status_code == 401
    assert "access_token" not in response.json()


async def test_at_hash_and_multiple_audience_authorized_party(login_server):
    client, provider, _, sign, claims, *_ = login_server
    digest = hashlib.sha256(provider["response"]["access_token"].encode()).digest()[:16]
    provider["response"]["id_token"] = sign(
        {
            **claims,
            "aud": ["finrisk-browser", "other"],
            "azp": "finrisk-browser",
            "at_hash": base64.urlsafe_b64encode(digest).decode().rstrip("="),
        }
    )
    assert (await client.post("/v1/auth/exchange", json=BODY)).status_code == 200


async def test_missing_nonce_or_forged_id_token_rejected(login_server):
    client, provider, _, sign, claims, *_ = login_server
    without_nonce = {key: value for key, value in claims.items() if key != "nonce"}
    provider["response"]["id_token"] = sign(without_nonce)
    assert (await client.post("/v1/auth/exchange", json=BODY)).status_code == 401
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider["response"]["id_token"] = jwt.encode(
        claims, other_key, algorithm="RS256", headers={"kid": "first"}
    )
    assert (await client.post("/v1/auth/exchange", json=BODY)).status_code == 401


async def test_valid_id_token_does_not_replace_api_authorization(login_server):
    client, provider, _, sign, _, access_claims, _ = login_server
    provider["response"]["access_token"] = sign({**access_claims, "scope": "openid"})
    assert (await client.post("/v1/auth/exchange", json=BODY)).status_code == 401


@pytest.mark.parametrize("status,expected", [(400, 401), (401, 401), (302, 503), (500, 503)])
async def test_provider_errors_are_not_reflected(login_server, status, expected):
    client, provider, *_ = login_server
    provider.update(status=status, response={"error_description": "provider-private-details"})
    response = await client.post("/v1/auth/exchange", json=BODY)
    assert response.status_code == expected
    assert "provider-private-details" not in response.text


@pytest.mark.parametrize("payload", [[], {}, {"token_type": "MAC"}, {"padding": "x" * 32769}])
async def test_malformed_or_oversized_provider_response(login_server, payload):
    client, provider, *_ = login_server
    provider["response"] = payload
    assert (await client.post("/v1/auth/exchange", json=BODY)).status_code == 503


async def test_exchange_requires_pkce_and_is_disabled_without_configuration(login_server):
    client, _, requests, *_, settings = login_server
    assert (
        await client.post("/v1/auth/exchange", json={**BODY, "code_verifier": "short"})
    ).status_code == 422
    assert not requests
    settings.browser_client_id = ""
    assert (await client.post("/v1/auth/exchange", json=BODY)).status_code == 404
    assert not requests


@pytest.mark.parametrize(
    "overrides",
    [
        {"browser_client_id": ""},
        {"browser_token_url": ""},
        {"browser_authorization_url": "http://issuer.example/authorize"},
        {"browser_token_url": "https://issuer.example/token?secret=oops"},
        {"browser_redirect_uri": "https://finrisk.example/other"},
        {"browser_redirect_uri": "https://user:pass@finrisk.example/auth/callback"},
        {"enable_dev_login": True},
        {"environment": "production", "browser_token_url": "http://localhost/token"},
    ],
)
def test_incomplete_or_unsafe_browser_configuration_rejected(overrides):
    with pytest.raises(ValidationError):
        config(**overrides)


async def test_callback_query_removed_from_asgi_scope():
    seen = []

    async def downstream(scope, receive, send):
        seen.append(scope["query_string"])

    scope = {"type": "http", "path": "/auth/callback", "query_string": b"code=private"}
    await CallbackPrivacy(downstream)(scope, None, None)
    assert seen == [b""]
    assert scope["query_string"] == b""
