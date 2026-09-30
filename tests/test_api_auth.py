import json
import time

import aiohttp
import jwt
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from pydantic import ValidationError

from services.api.auth import TokenVerifier
from services.api.settings import APISettings


def config(**overrides):
    values = dict(
        _env_file=None,
        _env_prefix="UNIT_API_",
        environment="test",
        allow_insecure_local=True,
        database_url="postgresql://test:test@localhost/test",
        oidc_issuer="https://issuer.example",
        oidc_jwks_url="https://issuer.example/jwks",
    )
    return APISettings(**{**values, **overrides})


def issue(key, kid="first", **overrides):
    now = int(time.time())
    claims = dict(
        iss="https://issuer.example",
        aud="finrisk-api",
        sub="alice",
        iat=now,
        exp=now + 300,
        scope="finrisk:access",
    )
    return jwt.encode({**claims, **overrides}, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def verifier(key):
    result = TokenVerifier(config(), None)
    result.keys = {"first": key.public_key()}
    result.expires = time.monotonic() + 300
    return result


async def test_valid_signed_access_token(verifier, key):
    identity = await verifier.verify(issue(key))
    assert identity.subject == "alice"
    assert identity.issuer == "https://issuer.example"


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": 1},
        {"aud": "different-api"},
        {"iss": "https://evil.example"},
        {"scope": "openid profile"},
        {"sub": ""},
        {"iat": True},
        {"nbf": int(time.time()) + 3600},
        {"iat": int(time.time()) + 3600},
    ],
)
async def test_invalid_claims_rejected(verifier, key, claims):
    with pytest.raises(HTTPException) as error:
        await verifier.verify(issue(key, **claims))
    assert error.value.status_code == 401


async def test_forged_signature_rejected(verifier):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as error:
        await verifier.verify(issue(other))
    assert error.value.status_code == 401


async def test_symmetric_algorithm_rejected(verifier):
    token = jwt.encode(
        {"sub": "alice"},
        "not-a-real-secret-but-long-enough-12345",
        algorithm="HS256",
        headers={"kid": "first"},
    )
    with pytest.raises(HTTPException) as error:
        await verifier.verify(token)
    assert error.value.status_code == 401


async def test_jwks_cache_rotation_and_unknown_key_throttle(key):
    next_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = [{**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": "first"}]
    requests = []

    async def jwks(request):
        requests.append(1)
        return web.json_response({"keys": keys})

    server_app = web.Application()
    server_app.router.add_get("/jwks", jwks)
    async with TestServer(server_app) as server, aiohttp.ClientSession() as session:
        verifier = TokenVerifier(config(oidc_jwks_url=str(server.make_url("/jwks"))), session)
        assert (await verifier.verify(issue(key))).subject == "alice"
        await verifier.verify(issue(key))
        assert len(requests) == 1
        for _ in range(3):
            with pytest.raises(HTTPException) as error:
                await verifier.verify(issue(key, kid="unknown"))
            assert error.value.status_code == 401
        assert len(requests) == 1
        keys.append(
            {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(next_key.public_key())), "kid": "next"}
        )
        verifier.last_refresh -= 6
        await verifier.verify(issue(next_key, kid="next"))
        assert len(requests) == 2


async def test_unavailable_jwks_fails_closed():
    async def unavailable(request):
        return web.Response(status=503)

    app = web.Application()
    app.router.add_get("/jwks", unavailable)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        verifier = TokenVerifier(config(oidc_jwks_url=str(server.make_url("/jwks"))), session)
        with pytest.raises(HTTPException) as error:
            await verifier._key("first")
        assert error.value.status_code == 503


def test_production_does_not_accept_local_identity_urls():
    with pytest.raises(ValidationError):
        config(environment="production", oidc_jwks_url="http://localhost/jwks")
