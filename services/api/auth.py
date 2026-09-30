import asyncio
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import aiohttp
import jwt
from fastapi import HTTPException


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str


def unauthorized():
    return HTTPException(
        401, "Invalid or missing access token", headers={"WWW-Authenticate": "Bearer"}
    )


class TokenVerifier:
    """Asynchronous JWKS cache. Never follow token-supplied key URLs or algorithms."""

    def __init__(self, settings, session):
        self.settings = settings
        self.session = session
        self.keys = {}
        self.expires = 0.0
        self.last_refresh = -float("inf")
        self.lock = asyncio.Lock()

    async def _key(self, kid):
        now = time.monotonic()
        if kid in self.keys and now < self.expires:
            return self.keys[kid]
        async with self.lock:
            now = time.monotonic()
            if kid in self.keys and now < self.expires:
                return self.keys[kid]
            if now - self.last_refresh < 5:
                if now >= self.expires:
                    raise HTTPException(503, "Identity provider unavailable")
                raise unauthorized()
            self.last_refresh = now
            try:
                async with self.session.get(
                    self.settings.oidc_jwks_url,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status != 200:
                        raise ValueError("JWKS fetch failed")
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(8192):
                        data.extend(chunk)
                        if len(data) > 65536:
                            raise ValueError("JWKS too large")
                document = json.loads(data)
                keys = {}
                for key in document["keys"]:
                    if (
                        key.get("kty") != "RSA"
                        or key.get("use", "sig") != "sig"
                        or key.get("alg", "RS256") != "RS256"
                    ):
                        continue
                    identifier = key.get("kid")
                    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128:
                        raise ValueError("Invalid key identifier")
                    if identifier in keys or "d" in key:
                        raise ValueError("Ambiguous or private signing key")
                    parsed = jwt.PyJWK.from_dict(key, algorithm="RS256").key
                    if parsed.key_size < 2048:
                        raise ValueError("Undersized signing key")
                    keys[identifier] = parsed
                if not keys:
                    raise ValueError("No supported signing keys")
            except (
                aiohttp.ClientError,
                TimeoutError,
                ValueError,
                KeyError,
                TypeError,
                jwt.PyJWTError,
                AttributeError,
            ):
                raise HTTPException(503, "Identity provider unavailable") from None
            self.keys = keys
            self.expires = time.monotonic() + self.settings.jwks_cache_seconds
            if kid not in keys:
                raise unauthorized()
            return keys[kid]

    async def verify(self, token):
        if not isinstance(token, str) or len(token) > 8192:
            raise unauthorized()
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or header.get("crit")
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 128
            ):
                raise unauthorized()
            key = await self._key(kid)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.settings.oidc_issuer,
                audience=self.settings.oidc_audience,
                leeway=self.settings.jwt_leeway_seconds,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            if (
                not isinstance(claims["sub"], str)
                or not 1 <= len(claims["sub"]) <= 255
                or any(ord(character) < 32 for character in claims["sub"])
                or any(type(claims[name]) is not int for name in ("exp", "iat"))
                or claims["exp"] <= claims["iat"]
            ):
                raise unauthorized()
            scope = claims.get("scope")
            if not isinstance(scope, str) or self.settings.required_scope not in scope.split():
                raise unauthorized()
            return Identity(claims["iss"], claims["sub"])
        except (jwt.PyJWTError, TypeError, ValueError):
            raise unauthorized() from None

    async def verify_id_token(self, token, *, nonce, access_token):
        """Validate the OIDC login assertion separately from API access authorization."""
        if not isinstance(token, str) or len(token) > 8192:
            raise unauthorized()
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or header.get("crit")
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 128
            ):
                raise unauthorized()
            claims = jwt.decode(
                token,
                await self._key(kid),
                algorithms=["RS256"],
                issuer=self.settings.oidc_issuer,
                audience=self.settings.browser_client_id,
                leeway=self.settings.jwt_leeway_seconds,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce"]},
            )
            if (
                not isinstance(claims["sub"], str)
                or not 1 <= len(claims["sub"]) <= 255
                or any(ord(character) < 32 for character in claims["sub"])
                or any(type(claims[name]) is not int for name in ("exp", "iat"))
                or claims["exp"] <= claims["iat"]
                or not isinstance(claims["nonce"], str)
                or not hmac.compare_digest(claims["nonce"].encode(), nonce.encode())
            ):
                raise unauthorized()
            audience = claims["aud"]
            if (isinstance(audience, list) and len(audience) > 1) or "azp" in claims:
                if claims.get("azp") != self.settings.browser_client_id:
                    raise unauthorized()
            if "at_hash" in claims:
                expected = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(access_token.encode("ascii")).digest()[:16]
                    )
                    .decode()
                    .rstrip("=")
                )
                if not isinstance(claims["at_hash"], str) or not hmac.compare_digest(
                    claims["at_hash"].encode(), expected.encode()
                ):
                    raise unauthorized()
            return Identity(claims["iss"], claims["sub"])
        except (jwt.PyJWTError, TypeError, ValueError):
            raise unauthorized() from None
