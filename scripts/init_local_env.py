"""Generate local-only credentials without printing them or overwriting an existing setup."""

import argparse
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace-legacy",
        action="store_true",
        help="Replace a ZeroMQ-only .env; refuses files containing FINRISK_DATABASE_URL",
    )
    args = parser.parse_args()
    path = Path(".env")
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if not args.replace_legacy or "FINRISK_DATABASE_URL" in existing:
            raise SystemExit(
                "Existing .env retained; update it explicitly or use a fresh workspace."
            )
        keys = {
            line.split("=", 1)[0].strip()
            for line in existing.splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        legacy_keys = {
            "MARKET_DATA_ZMQ_PUB_ENDPOINT",
            "MARKET_DATA_ZMQ_PUBLIC_KEY",
            "MARKET_DATA_ZMQ_SECRET_KEY",
            "INGESTION_ZMQ_SUB_ENDPOINT",
            "INGESTION_MARKET_DATA_PUBLIC_KEY",
            "INGESTION_ZMQ_CLEAN_PUB_ENDPOINT",
            "INGESTION_ZMQ_PUBLIC_KEY",
            "INGESTION_ZMQ_SECRET_KEY",
        }
        if not keys or not keys.issubset(legacy_keys):
            raise SystemExit(
                "Refusing to replace a file with settings outside the legacy ZeroMQ setup."
            )
    password = secrets.token_urlsafe(32)
    template = Path(".env.example").read_text(encoding="utf-8")
    path.write_text(
        template.replace("replace-with-generated-local-password", password), encoding="utf-8"
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print("Local .env generated. Retired ZeroMQ keys are not used by this pipeline.")
    import runpy

    runpy.run_path(str(Path(__file__).with_name("init_api_env.py")), run_name="__main__")


if __name__ == "__main__":
    main()
