"""Re-identification helpers for logging.

Provides:
- deterministic_id(value): HMAC-SHA256 prefix for correlation (non-reversible, safe)
- encrypt_value(value): reversible encryption (Fernet) when key available
- decrypt_value(token): reverse of encrypt_value

Environment variables:
- LOG_HMAC_KEY: base64, hex, or raw key for deterministic HMAC (optional)
- LOG_FERNET_KEY: base64/hex/raw 32-byte key for Fernet (optional)

If keys are not present, functions fall back to safe defaults (HMAC fallback to sha256, encrypt/decrypt disabled).
"""
from __future__ import annotations

import os
import base64
import hashlib
import hmac
from typing import Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False
    Fernet = None
    InvalidToken = Exception


def _read_env_str(name: str) -> Optional[str]:
    val = os.getenv(name)
    if not val:
        return None
    return val


def _parse_hmac_key(val: str) -> Optional[bytes]:
    """Parse HMAC key from hex, base64, or raw string to bytes.

    Try hex first to correctly handle hex-encoded ASCII (which can look like
    valid base64), then fall back to base64, then raw UTF-8 encoding.
    """
    if not val:
        return None
    # Try hex first
    try:
        decoded = bytes.fromhex(val)
        if len(decoded) > 0:
            return decoded
    except Exception:
        pass
    # Then try base64
    try:
        decoded = base64.b64decode(val, validate=True)
        if len(decoded) > 0:
            return decoded
    except Exception:
        pass
    # Fallback to utf-8 bytes
    return val.encode("utf-8")


def _parse_fernet_key(val: str) -> Optional[bytes]:
    """Return a URL-safe base64-encoded Fernet key (bytes) or None.

    Accepts:
    - A valid Fernet key (base64, decodes to 32 bytes): returned as bytes
    - Raw 32-byte hex or raw 32-char string: converted to base64
    - Hex-encoded 32-byte value
    """
    if not val:
        return None
    # If already a base64 urlsafe key that decodes to 32 bytes, use as-is
    try:
        raw = base64.urlsafe_b64decode(val)
        if len(raw) == 32:
            return val.encode("utf-8")
    except Exception:
        pass

    # If provided as hex for 32 bytes
    try:
        raw = bytes.fromhex(val)
        if len(raw) == 32:
            return base64.urlsafe_b64encode(raw)
    except Exception:
        pass

    # If provided as raw 32-byte string
    try:
        raw = val.encode("utf-8")
        if len(raw) == 32:
            return base64.urlsafe_b64encode(raw)
    except Exception:
        pass

    return None


_HMAC_KEY = None
_FERNET_KEY_B64 = None

_hmac_val = _read_env_str("LOG_HMAC_KEY")
if _hmac_val:
    _HMAC_KEY = _parse_hmac_key(_hmac_val)

_fernet_val = _read_env_str("LOG_FERNET_KEY")
if _fernet_val:
    _FERNET_KEY_B64 = _parse_fernet_key(_fernet_val)


def deterministic_id(value: str, length: int = 8) -> str:
    """Produce a deterministic short id for correlation using HMAC if key available,
    otherwise SHA256 prefix. Returns like 'sym_ab12cd34'.
    """
    if not value:
        return "<none>"
    if _HMAC_KEY:
        mac = hmac.new(_HMAC_KEY, value.upper().encode("utf-8"), hashlib.sha256).hexdigest()
        return f"sym_{mac[:length]}"
    # fallback
    h = hashlib.sha256(value.upper().encode("utf-8")).hexdigest()
    return f"sym_{h[:length]}"


# Fernet-based reversible encryption (optional)

def _ensure_fernet_key():
    """Load the Fernet key from the environment on each call.

    This ensures tests that set or delete LOG_FERNET_KEY at runtime are respected
    and the cached _FERNET_KEY_B64 is cleared when the env var is removed.
    """
    global _FERNET_KEY_B64
    if not _HAS_CRYPTO:
        _FERNET_KEY_B64 = None
        return
    val = _read_env_str("LOG_FERNET_KEY")
    if not val:
        _FERNET_KEY_B64 = None
        return
    _FERNET_KEY_B64 = _parse_fernet_key(val)


def encrypt_value(value: str) -> Optional[str]:
    if not value:
        return None
    if not _HAS_CRYPTO:
        return None
    # Ensure key is loaded in case env was set/removed after module import
    _ensure_fernet_key()
    if not _FERNET_KEY_B64:
        return None
    try:
        f = Fernet(_FERNET_KEY_B64)
        token = f.encrypt(value.encode("utf-8"))
        return token.decode("utf-8")
    except Exception:
        return None


def decrypt_value(token: str) -> Optional[str]:
    if not token:
        return None
    if not _HAS_CRYPTO:
        return None
    # Ensure key is loaded in case env was set/removed after module import
    _ensure_fernet_key()
    if not _FERNET_KEY_B64:
        return None
    try:
        f = Fernet(_FERNET_KEY_B64)
        data = f.decrypt(token.encode("utf-8"))
        return data.decode("utf-8")
    except InvalidToken:
        return None
    except Exception:
        return None


# Helpers for tests/dev to generate keys
def generate_fernet_key() -> str:
    if not _HAS_CRYPTO:
        raise RuntimeError("cryptography package not available")
    return Fernet.generate_key().decode("utf-8")


def generate_hmac_key() -> str:
    # 32 bytes random base64
    return base64.b64encode(os.urandom(32)).decode("utf-8")
