"""Example logging configuration using dictConfig.

This file demonstrates declarative logging setup. Use it as a template
and pass to load_from_dict_config() in logging_config.py.

Environment variables:
- LOG_LEVEL: logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- LOG_HMAC_KEY: base64/hex/raw key for deterministic HMAC (optional)
- LOG_FERNET_KEY: base64/hex/raw 32-byte key for Fernet encryption (optional)
- LOG_USE_QUEUE: enable non-blocking queue handler (true/false)
"""

LOGGING_CONFIG_DEVELOPMENT = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
        },
        "simple": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        },
    },
    "filters": {
        "correlation": {
            "()": "services.logging_filter.CorrelationIdFilter"
        },
        "redaction": {
            "()": "services.logging_filter.RedactionFilter"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "json",
            "stream": "ext://sys.stdout",
            "filters": ["correlation", "redaction"],
        },
    },
    "loggers": {
        "asyncio": {"level": "WARNING"},
        "websockets": {"level": "WARNING"},
    },
    "root": {
        "level": "$(LOG_LEVEL)",
        "handlers": ["console"],
    },
}

LOGGING_CONFIG_PRODUCTION = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
        },
    },
    "filters": {
        "correlation": {
            "()": "services.logging_filter.CorrelationIdFilter"
        },
        "redaction": {
            "()": "services.logging_filter.RedactionFilter"
        },
    },
    "handlers": {
        "queue": {
            "class": "logging.handlers.QueueHandler",
            "queue": "ext://queue.Queue",
        },
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "json",
            "stream": "ext://sys.stdout",
            "filters": ["correlation", "redaction"],
        },
    },
    "loggers": {
        "asyncio": {"level": "ERROR"},
        "websockets": {"level": "ERROR"},
    },
    "root": {
        "level": "$(LOG_LEVEL)",
        "handlers": ["queue"],
    },
}


def get_config_for_env(env: str = "development") -> dict:
    """Get logging config for the given environment.

    Args:
        env: 'development', 'production', or custom environment name

    Returns:
        Dictionary suitable for load_from_dict_config()
    """
    if env.lower() == "production":
        return LOGGING_CONFIG_PRODUCTION
    return LOGGING_CONFIG_DEVELOPMENT


# Usage example:
# from services.logging_config import load_from_dict_config
# from services.logging_example_config import get_config_for_env
#
# config = get_config_for_env("production")
# load_from_dict_config(config)
