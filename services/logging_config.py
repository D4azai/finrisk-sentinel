"""Central logging configuration: structured JSON output + redaction and correlation filters.

Call configure_app_logging() at process startup.

Design:
- Non-blocking logging using QueueHandler + QueueListener
- JSON formatter (python-json-logger if available) with ISO8601 timestamps
- CorrelationIdFilter (contextvar) + RedactionFilter installed on consumer handlers
- Listener is stored on module to avoid GC
"""
from __future__ import annotations

import logging
import logging.config
import logging.handlers
import sys
import queue
from datetime import datetime, timezone

from services.logging_filter import RedactionFilter, CorrelationIdFilter

try:
    from pythonjsonlogger import jsonlogger  # type: ignore
    _HAS_JSONLOGGER = True
except Exception:
    _HAS_JSONLOGGER = False


class SimpleJsonFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # ISO8601 with UTC timezone
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.isoformat()

    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Include exc info if present
        if record.exc_info:
            try:
                base["exc"] = self.formatException(record.exc_info)
            except Exception:
                base["exc"] = "<exc-format-error>"

        # Merge extra keys from record.__dict__ (skip standard attrs)
        skip = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
        }
        for k, v in record.__dict__.items():
            if k.startswith("_") or k in skip:
                continue
            try:
                # ensure serialisable
                logging.Formatter().formatMessage({"msg": v})  # cheap check
                base[k] = v
            except Exception:
                base[k] = str(v)
        import json

        return json.dumps(base, default=str)


# Module-level listener to keep it alive
_LOG_QUEUE_LISTENER: logging.handlers.QueueListener | None = None


def init_logging(level: int = logging.INFO, use_queue: bool = True) -> None:
    """Initialize logging for the process.

    - use_queue: when True, log records are pushed to a queue to avoid blocking
      critical application threads. A QueueListener delivers records to real
      handlers.
    """
    root = logging.getLogger()
    # Remove existing handlers to avoid duplicate logs
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(level)

    # Build formatter
    if _HAS_JSONLOGGER:
        fmt = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    else:
        fmt = SimpleJsonFormatter()

    # Destination handler(s) that actually emit logs
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    # Attach filters to consumer handlers
    console_handler.addFilter(CorrelationIdFilter())
    console_handler.addFilter(RedactionFilter())

    if use_queue:
        q: queue.Queue = queue.Queue(-1)
        queue_handler = logging.handlers.QueueHandler(q)
        root.addHandler(queue_handler)

        listener = logging.handlers.QueueListener(q, console_handler, respect_handler_level=True)
        listener.start()

        # keep reference so GC doesn't stop the listener
        global _LOG_QUEUE_LISTENER
        _LOG_QUEUE_LISTENER = listener
    else:
        root.addHandler(console_handler)

    # Prevent library loggers from being too noisy by default
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def load_from_dict_config(config_dict: dict) -> None:
    """Load logging configuration from a dictionary (declarative config).

    Supports env variable interpolation in config values via $(VAR_NAME) syntax.
    Call this instead of init_logging() if you want full control via dictConfig.

    Example:
        config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {"()": "pythonjsonlogger.jsonlogger.JsonFormatter"}
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout"
                }
            },
            "root": {"level": "$(LOG_LEVEL)", "handlers": ["console"]}
        }
        load_from_dict_config(config)
    """
    import os

    def interpolate_env(obj: any) -> any:
        """Recursively replace $(VAR) with environment variables."""
        if isinstance(obj, str):
            # Replace $(VAR_NAME) with os.getenv("VAR_NAME")
            import re
            def replacer(match):
                var_name = match.group(1)
                return os.getenv(var_name, match.group(0))
            return re.sub(r"\$\((\w+)\)", replacer, obj)
        if isinstance(obj, dict):
            return {k: interpolate_env(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [interpolate_env(v) for v in obj]
        return obj

    # Interpolate environment variables
    config_dict = interpolate_env(config_dict)

    # Apply dictConfig
    logging.config.dictConfig(config_dict)
    
    # Store listener if QueueListener is configured
    global _LOG_QUEUE_LISTENER
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.QueueHandler):
            # Locate the QueueListener (it should be in the config's handlers)
            for h in root.handlers:
                if isinstance(h, logging.handlers.QueueListener):
                    _LOG_QUEUE_LISTENER = h
                    break
            break


# Convenience wrapper used by modules
def configure_app_logging():
    # Respect environment LOG_LEVEL if present
    import os

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    try:
        level = getattr(logging, level_name)
    except Exception:
        level = logging.INFO

    use_queue = os.getenv("LOG_USE_QUEUE", "true").lower() not in ("0", "false", "no")
    init_logging(level=level, use_queue=use_queue)
