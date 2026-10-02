"""Pinned-endpoint token exchange for a public Authorization Code + PKCE client."""

import json
import logging
import time
from urllib.parse import urlsplit

import aiohttp
import jwt
from fastapi import HTTPException, Request
from pydantic import Field

from services.api.auth import unauthorized
from services.api.models import StrictBody

logger = logging.getLogger(__name__)


class CodeExchange(StrictBody):
    code: str = Field(min_length=1, max_length=4096, pattern=r"^[^\s\x00-\x1f\x7f]+$")
    code_verifier: str = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$")
    nonce: str = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def browser_config(settings):
    if not settings.browser_client_id:
        return None
    return {
        "client_id": settings.browser_client_id,
        "authorization_url": settings.browser_authorization_url,
        "redirect_uri": settings.browser_redirect_uri,
        "issuer": settings.oidc_issuer,
        "scope": " ".join(dict.fromkeys(["openid", settings.required_scope])),
        "audience": settings.browser_auth_audience or None,
    }


def register_browser_auth(app):
    @app.post("/v1/auth/exchange")
    async def exchange(body: CodeExchange, request: Request):
        settings = request.app.state.settings
        if not settings.browser_client_id:
            raise HTTPException(404, "Browser login disabled")
        redirect = urlsplit(settings.browser_redirect_uri)
        if request.headers.get("origin") != f"{redirect.scheme}://{redirect.netloc}":
            raise HTTPException(403, "Sign-in must originate from the configured application")
        try:
            async with request.app.state.http.post(
                settings.browser_token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.browser_client_id,
                    "redirect_uri": settings.browser_redirect_uri,
                    "code": body.code,
                    "code_verifier": body.code_verifier,
                },
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Browser identity token exchange rejected",
                        extra={"provider_status": response.status},
                    )
                    if response.status in {400, 401, 403}:
                        raise HTTPException(401, "Sign-in expired or was refused; start again")
                    raise HTTPException(503, "Identity provider unavailable")
                raw = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    raw.extend(chunk)
                    if len(raw) > 32768:
                        raise ValueError("Oversized token response")
                data = json.loads(raw)
                if (
                    not isinstance(data, dict)
                    or not isinstance(data.get("token_type"), str)
                    or data["token_type"].lower() != "bearer"
                    or not isinstance(data.get("access_token"), str)
                    or not isinstance(data.get("id_token"), str)
                ):
                    raise ValueError("Invalid token response")
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
            raise HTTPException(503, "Identity provider unavailable") from None
        verifier = request.app.state.verifier
        try:
            identity = await verifier.verify(data["access_token"])
        except HTTPException:
            try:
                header = jwt.get_unverified_header(data["access_token"])
                claims = jwt.decode(data["access_token"], options={"verify_signature": False})
                audience = claims.get("aud")
                audience_matches = (
                    settings.oidc_audience == audience
                    or isinstance(audience, list)
                    and settings.oidc_audience in audience
                )
                scope = claims.get("scope")
                scope_matches = isinstance(scope, str) and (
                    settings.required_scope in scope.split()
                )
                logger.warning(
                    "Browser access token validation failed "
                    "(alg_rs256=%s issuer_matches=%s audience_matches=%s "
                    "scope_matches=%s has_subject=%s integer_times=%s)",
                    header.get("alg") == "RS256",
                    claims.get("iss") == settings.oidc_issuer,
                    audience_matches,
                    scope_matches,
                    isinstance(claims.get("sub"), str),
                    all(type(claims.get(name)) is int for name in ("iat", "exp")),
                )
            except (jwt.PyJWTError, TypeError, ValueError):
                logger.warning("Browser access token is not a decodable JWT")
            raise
        try:
            login_identity = await verifier.verify_id_token(
                data["id_token"], nonce=body.nonce, access_token=data["access_token"]
            )
        except HTTPException:
            logger.warning("Browser ID token validation failed")
            raise
        if identity != login_identity:
            raise unauthorized()
        # Signature and all authorization claims were checked above.
        claims = jwt.decode(data["access_token"], options={"verify_signature": False})
        expires_in = claims["exp"] - int(time.time())
        if expires_in <= 0:
            raise unauthorized()
        return {"access_token": data["access_token"], "expires_in": expires_in}
