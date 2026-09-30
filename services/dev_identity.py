"""Local development token issuer. Not a production login provider."""

import json
import os
import time
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: Literal["alice", "bob"]


@asynccontextmanager
async def lifespan(app):
    if os.getenv("DEV_IDENTITY_ENABLED") != "true" or os.getenv("API_ENVIRONMENT") != "development":
        raise RuntimeError("Development issuer requires explicit development-only enablement")
    app.state.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.kid = str(uuid4())
    yield


app = FastAPI(title="LOCAL DEVELOPMENT identity issuer", lifespan=lifespan)


@app.get("/live")
async def live():
    return {"alive": True}


@app.get("/jwks")
async def jwks():
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(app.state.key.public_key()))
    return {"keys": [{**key, "kid": app.state.kid, "use": "sig", "alg": "RS256"}]}


@app.post("/token")
async def token(body: Login):
    if os.getenv("API_ENVIRONMENT") != "development":
        raise HTTPException(404)
    now = int(time.time())
    encoded = jwt.encode(
        {
            "iss": os.environ["API_OIDC_ISSUER"],
            "aud": "finrisk-api",
            "sub": f"dev:{body.user}",
            "iat": now,
            "exp": now + 600,
            "scope": "finrisk:access",
        },
        app.state.key,
        algorithm="RS256",
        headers={"kid": app.state.kid, "typ": "at+jwt"},
    )
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {"access_token": encoded, "token_type": "Bearer", "expires_in": 600},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
