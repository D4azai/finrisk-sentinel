import base64
import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import aiohttp
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.api.browser_auth import browser_config, register_browser_auth
from services.api.models import StrictBody


class DemoLogin(StrictBody):
    user: Literal["alice", "bob"]


class CallbackPrivacy:
    """The callback query is for browser JS only; omit it from ASGI access logs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/auth/callback":
            scope["query_string"] = b""
        await self.app(scope, receive, send)


def _frontend_content_security_policy(page: Path) -> str:
    """Allow only the exact inline bootstrap payloads emitted by Next's static export."""
    markup = page.read_text(encoding="utf-8")
    hashes = []
    for match in re.finditer(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", markup, re.DOTALL):
        if re.search(r"\bsrc\s*=", match.group("attrs"), re.IGNORECASE):
            continue
        digest = hashlib.sha256(match.group("body").encode()).digest()
        hashes.append(f"'sha256-{base64.b64encode(digest).decode()}'")
    scripts = " ".join(["'self'", *hashes])
    return (
        f"default-src 'self'; script-src {scripts}; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )


def register_web(app):
    app.add_middleware(CallbackPrivacy)
    register_browser_auth(app)
    directory = Path(__file__).parent / "static"
    index_page = directory / "index.html"
    content_security_policy = _frontend_content_security_policy(index_page)
    app.mount("/_next", StaticFiles(directory=directory / "_next"), name="next-assets")

    @app.get("/browser-auth.js", include_in_schema=False)
    async def browser_auth_script():
        return FileResponse(directory / "browser-auth.js", media_type="text/javascript")

    @app.get("/app-runtime.js", include_in_schema=False)
    async def app_runtime_script():
        return FileResponse(directory / "app-runtime.js", media_type="text/javascript")

    @app.get("/app-bootstrap.js", include_in_schema=False)
    async def app_bootstrap_script():
        return FileResponse(directory / "app-bootstrap.js", media_type="text/javascript")

    @app.get("/", include_in_schema=False)
    @app.get("/auth/callback", include_in_schema=False)
    async def dashboard():
        return FileResponse(
            index_page,
            headers={
                "Content-Security-Policy": content_security_policy,
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.get("/v1/app-config")
    async def config(request: Request):
        settings = request.app.state.settings
        return {
            "development_login": settings.enable_dev_login
            and settings.environment == "development",
            "demo_data": settings.allow_demo_market_data,
            "paper_trading": settings.enable_paper_trading,
            "live_trading": False,
            "browser_login": browser_config(settings),
        }

    @app.post("/v1/dev-login")
    async def login(body: DemoLogin, request: Request):
        settings = request.app.state.settings
        if (
            settings.environment != "development"
            or not settings.enable_dev_login
            or not settings.allow_insecure_local
        ):
            raise HTTPException(404, "Development login disabled")
        url = urlsplit(settings.oidc_jwks_url)
        if url.scheme != "http" or url.hostname not in {"dev_identity", "localhost", "127.0.0.1"}:
            raise HTTPException(503, "Local issuer is not configured")
        try:
            async with request.app.state.http.post(
                urljoin(settings.oidc_jwks_url, "token"),
                json={"user": body.user},
                timeout=aiohttp.ClientTimeout(total=5),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise HTTPException(503, "Local sign-in is unavailable")
                raw = await response.content.read(16385)
                if len(raw) > 16384:
                    raise HTTPException(503, "Invalid issuer response")
                import json

                data = json.loads(raw)
                if not isinstance(data.get("access_token"), str):
                    raise ValueError("Missing access token")
                return {
                    "access_token": data["access_token"],
                    "expires_in": data.get("expires_in", 600),
                }
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise HTTPException(503, "Local sign-in is unavailable") from error
