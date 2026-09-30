from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="API_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    environment: Literal["production", "development", "test"] = "production"
    database_url: SecretStr
    oidc_issuer: str
    oidc_audience: str = "finrisk-api"
    oidc_jwks_url: str
    required_scope: str = "finrisk:access"
    allow_insecure_local: bool = False
    allow_demo_market_data: bool = False
    enable_paper_trading: bool = False
    enable_dev_login: bool = False
    browser_client_id: str = Field(default="", max_length=255)
    browser_authorization_url: str = ""
    browser_token_url: str = ""
    browser_redirect_uri: str = ""
    browser_auth_audience: str = ""
    jwt_leeway_seconds: int = Field(default=5, ge=0, le=30)
    jwks_cache_seconds: int = Field(default=300, ge=30, le=3600)
    pool_size: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def secure_endpoints(self):
        if self.environment == "production" and (
            self.enable_paper_trading or self.enable_dev_login
        ):
            raise ValueError("Demo trading and development login are forbidden in production")
        if self.enable_paper_trading and not self.allow_demo_market_data:
            raise ValueError("Paper trading requires demo market data")
        if self.environment == "production" and self.allow_demo_market_data:
            raise ValueError("Demo market data is not permitted in production")
        local = self.environment != "production" and self.allow_insecure_local
        browser_urls = (
            self.browser_authorization_url,
            self.browser_token_url,
            self.browser_redirect_uri,
        )
        if self.browser_client_id or any(browser_urls) or self.browser_auth_audience:
            if not self.browser_client_id.strip() or not all(browser_urls):
                raise ValueError(
                    "Browser login requires client ID, authorization/token URLs and redirect URI"
                )
            if self.enable_dev_login:
                raise ValueError("Configure either browser login or development login")
            for value in browser_urls:
                url = urlsplit(value)
                if (
                    not url.hostname
                    or url.username
                    or url.password
                    or url.fragment
                    or url.query
                    or any(character.isspace() for character in value)
                    or "\\" in value
                ):
                    raise ValueError("Invalid browser login URL")
                if url.scheme != "https" and not (
                    local
                    and url.scheme == "http"
                    and url.hostname in {"localhost", "127.0.0.1", "::1"}
                ):
                    raise ValueError(
                        "Browser login requires HTTPS, except explicit loopback development"
                    )
            if urlsplit(self.browser_redirect_uri).path != "/auth/callback":
                raise ValueError("Browser redirect URI must use /auth/callback")
        for value in (self.oidc_issuer, self.oidc_jwks_url):
            url = urlsplit(value)
            if not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("Invalid identity-provider URL")
            if url.scheme != "https" and not (local and url.scheme == "http"):
                raise ValueError("Identity endpoints require HTTPS outside explicit local mode")
        db = urlsplit(self.database_url.get_secret_value())
        if db.scheme not in {"postgres", "postgresql"} or not db.hostname:
            raise ValueError("PostgreSQL URL required")
        if not local and parse_qs(db.query).get("sslmode") != ["verify-full"]:
            raise ValueError("Database TLS verification is required")
        if not self.oidc_audience or not self.required_scope:
            raise ValueError("An API audience and access scope are required")
        return self
