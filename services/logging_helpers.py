"""Helpers for safe, structured logging and redaction.

Design goals:
- Deterministic symbol obfuscation for correlation without exposing real symbols.
- Recursive redaction of common sensitive keys for logs.
- Non-destructive: do not modify payloads in-memory; redaction returns a copy for logging only.
- Extensible: single place to change mask keys or switch to reversible encryption.

Usage examples:
  from services.logging_helpers import redact_symbol, redact_payload
  logger.info("ingested %s", redact_symbol(symbol))
  logger.debug("payload: %s", redact_payload(payload))

Notes on re-injection: do NOT store redacted values back to DB. If later re-identification is required, use a secure mapping (KMS-wrapped reversible encryption) kept out-of-band.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable

# Keys considered sensitive for logging purposes. Lowercased when compared.
DEFAULT_SENSITIVE_KEYS = {"s", "symbol", "secret", "token", "api_key", "password", "account"}


def _short_hex(value: str, length: int = 8) -> str:
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return h[:length]


def redact_symbol(symbol: str | None) -> str:
    """Return a deterministic obfuscated symbol (safe for logs).

    Keeps correlation across logs while preventing disclosure of real trading symbols.
    """
    if not symbol:
        return "<none>"
    # Normalise to uppercase for stable hashing
    return f"sym_{_short_hex(symbol.upper())}"


def redact_value(val: Any) -> Any:
    if isinstance(val, str):
        return f"<redacted:{_short_hex(val)}>"
    if isinstance(val, (int, float)):
        return "<redacted:number>"
    return "<redacted>"


def redact_payload(obj: Any, keys_to_mask: Iterable[str] | None = None) -> Any:
    """Recursively redact sensitive keys in dicts/lists and return a copy safe for logging.

    Does not modify the input object.
    """
    mask = set(k.lower() for k in (keys_to_mask or DEFAULT_SENSITIVE_KEYS))

    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if k.lower() in mask:
                out[k] = redact_value(v)
            else:
                out[k] = redact_payload(v, mask)
        return out
    if isinstance(obj, list):
        return [redact_payload(x, mask) for x in obj]
    return obj
