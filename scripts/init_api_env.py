"""Add API-only local credentials without changing the existing pipeline credentials."""

import secrets
from pathlib import Path

from dotenv import dotenv_values


def main():
    path = Path(".env")
    if not path.exists():
        raise SystemExit("Run scripts/init_local_env.py first")
    current = dotenv_values(path)
    if current.get("FINRISK_ENVIRONMENT") != "development":
        raise SystemExit("This initializer only supports the local development environment")
    password = current.get("API_DATABASE_PASSWORD") or secrets.token_urlsafe(32)
    defaults = {
        "API_DATABASE_PASSWORD": password,
        "API_DATABASE_URL": f"postgresql://finrisk_api_login:{password}@postgres:5432/finrisk",
        "API_ENVIRONMENT": "development",
        "API_ALLOW_INSECURE_LOCAL": "true",
        "API_OIDC_ISSUER": "http://localhost:8081",
        "API_OIDC_JWKS_URL": "http://dev_identity:8080/jwks",
        "API_OIDC_AUDIENCE": "finrisk-api",
    }
    additions = {key: value for key, value in defaults.items() if key not in current}
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + "\n".join(f"{key}={value}" for key, value in additions.items()) + "\n")
    print("Local API settings initialized; existing credentials were preserved.")


if __name__ == "__main__":
    main()
