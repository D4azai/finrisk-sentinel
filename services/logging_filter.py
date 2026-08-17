"""A logging.Filter that redacts sensitive data from LogRecord.args and common extras.

Adds redacted variants into the record so structured formatters can include them.
Also provides a CorrelationIdFilter that injects a correlation_id (contextvar) into every record.
"""
from __future__ import annotations

import logging
import re
import contextvars
from typing import Any, Optional

from services.logging_helpers import redact_payload
from services.logging_crypto import deterministic_id, encrypt_value

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{3,12}$")

# Contextvar for correlation id / trace id
_CORRELATION_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("correlation_id", default=None)


def set_correlation_id(cid: Optional[str]) -> None:
    """Set the correlation id for the current context (async-safe)."""
    if cid is None:
        # reset by setting None
        _CORRELATION_ID.set(None)
    else:
        _CORRELATION_ID.set(cid)


def get_correlation_id() -> Optional[str]:
    return _CORRELATION_ID.get()


class CorrelationIdFilter(logging.Filter):
    """Injects `correlation_id` into each LogRecord from contextvars.

    This enables per-request/task correlation in async applications.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        cid = get_correlation_id()
        if cid:
            record.__dict__["correlation_id"] = cid
        else:
            # keep explicit 'none' rather than missing key to simplify downstream processing
            record.__dict__["correlation_id"] = None
        return True


def _redact_arg(arg: Any) -> Any:
    # If dict/list -> redact payload recursively
    if isinstance(arg, dict) or isinstance(arg, list):
        return redact_payload(arg)
    # If looks like a symbol (e.g., BTCUSDT) -> deterministic id
    if isinstance(arg, str):
        if _SYMBOL_PATTERN.match(arg.upper()):
            return deterministic_id(arg)
    return arg


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Redact tuple/list args
        if hasattr(record, "args") and record.args:
            try:
                if isinstance(record.args, tuple):
                    record.__dict__["args_redacted"] = tuple(_redact_arg(a) for a in record.args)
                elif isinstance(record.args, dict):
                    # dict-style formatting
                    record.__dict__["args_redacted"] = {k: _redact_arg(v) for k, v in record.args.items()}
            except Exception:
                # Never block logging due to redaction errors
                pass

        # If structured extras present, redact common keys and add redacted versions
        try:
            for key in ("payload", "raw_payload", "payload_bytes"):
                if key in record.__dict__:
                    val = record.__dict__[key]
                    record.__dict__[f"{key}_redacted"] = redact_payload(val)

            # symbol extras
            for sym_key in ("symbol", "s"):
                if sym_key in record.__dict__:
                    try:
                        sym = record.__dict__[sym_key]
                        record.__dict__["symbol_redacted"] = deterministic_id(sym)
                        enc = encrypt_value(sym)
                        if enc:
                            record.__dict__["symbol_encrypted"] = enc
                    except Exception:
                        # Do not block logging
                        pass
        except Exception:
            pass

        return True
