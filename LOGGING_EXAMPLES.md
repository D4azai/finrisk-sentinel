# Logging System Examples

This document provides practical examples for using the FinRisk Sentinel logging system.

## Table of Contents
1. [Basic Setup](#basic-setup)
2. [Correlation IDs](#correlation-ids)
3. [Redaction](#redaction)
4. [Encryption](#encryption)
5. [Configuration Patterns](#configuration-patterns)
6. [Testing](#testing)

---

## Basic Setup

### Minimal Application

```python
# main.py
import logging
from logging.logging_config import configure_app_logging

# Initialize logging at startup
configure_app_logging()

# Use standard logging
logger = logging.getLogger(__name__)


async def main():
    logger.info("Application started")
    # ... rest of code ...
```

**Environment:**
```bash
export LOG_LEVEL=DEBUG
export LOG_USE_QUEUE=true
python main.py
```

**Output:**
```json
{"ts": "2026-08-17T22:30:56.637Z", "level": "INFO", "logger": "__main__", "msg": "Application started"}
```

---

## Correlation IDs

### Request Tracing in Async Application

```python
# services/market_data/ingestion_handler.py
import logging
from logging.logging_filter import set_correlation_id, get_correlation_id

logger = logging.getLogger(__name__)


async def process_trade_stream(request_id: str, data_stream):
    # Set correlation ID for this task/request
    set_correlation_id(request_id)

    try:
        async for trade in data_stream:
            # All logs in this context automatically include correlation_id
            logger.info("Processing trade", extra={
                "symbol": trade.symbol,
                "price": trade.price,
            })
    finally:
        # Clean up
        set_correlation_id(None)


# In async handler:
async def handle_client_request(request):
    request_id = request.headers.get("X-Request-ID", "unknown")
    await process_trade_stream(request_id, stream)
```

**Log Output:**
```json
{
  "ts": "2026-08-17T22:30:56.637Z",
  "level": "INFO",
  "logger": "services.market_data.ingestion_handler",
  "msg": "Processing trade",
  "correlation_id": "req-client-12345",
  "symbol_redacted": "sym_8a9b2c1f",
  "price": 45123.50
}
```

### Multi-Step Workflow

```python
# services/ingestion/pipeline.py
import logging
from logging.logging_filter import set_correlation_id
from uuid import uuid4

logger = logging.getLogger(__name__)


class TradeProcessor:
    async def process_batch(self, trades: list):
        batch_id = f"batch_{uuid4()}"
        set_correlation_id(batch_id)

        try:
            logger.info(f"Starting batch processing", extra={"count": len(trades)})

            for i, trade in enumerate(trades):
                logger.debug(f"Processing trade {i + 1}/{len(trades)}")
                await self._validate_trade(trade)
                await self._normalize_trade(trade)

            logger.info("Batch completed successfully")
        except Exception as e:
            logger.error(f"Batch failed: {e}", exc_info=True)
            raise
        finally:
            set_correlation_id(None)
```

---

## Redaction

### Automatic Redaction of Sensitive Fields

```python
# services/market_data/connector.py
import logging
from services.logging_helpers import redact_payload

logger = logging.getLogger(__name__)


async def on_message(raw_payload: dict):
    # Sensitive keys are automatically redacted
    logger.debug(
        "Raw message received",
        extra={
            "payload": raw_payload,  # Will be logged as payload_redacted
            "symbol": "BTCUSDT",  # Will be logged as symbol_redacted
        }
    )
```

**Log Output:**
```json
{
  "ts": "2026-08-17T22:30:56.637Z",
  "level": "DEBUG",
  "msg": "Raw message received",
  "payload_redacted": {
    "p": "<redacted:number>",
    "q": "<redacted:number>",
    "t": 1692288656637,
    "secret": "<redacted:8af1b2d>"
  },
  "symbol_redacted": "sym_ab8c2f1d"
}
```

### Custom Redaction

```python
from services.logging_helpers import redact_symbol, redact_payload

# Redact a single symbol
obfuscated_symbol = redact_symbol("BTCUSDT")  # "sym_ab8c2f1d"

# Redact nested payloads
trade_data = {
    "symbol": "ETHUSDT",
    "price": 2345.67,
    "account": "user_123",
    "nested": {
        "api_key": "sk_live_abc123",
        "timestamp": 1692288656637,
    }
}
safe_log = redact_payload(trade_data)
logger.info("Trade data", extra={"data": safe_log})
```

---

## Encryption

### Setup

```bash
# Generate Fernet key for reversible encryption
python -c "from services.logging_crypto import generate_fernet_key; print(generate_fernet_key())"
# Output: h5OmGXP_y3WZN8F2XJ0aBc1D2E3F4G5H6I7J8K9L0=

# Set in .env
export LOG_FERNET_KEY=h5OmGXP_y3WZN8F2XJ0aBc1D2E3F4G5H6I7J8K9L0=
```

### Encrypt/Decrypt Usage

```python
from logging.logging_crypto import encrypt_value, decrypt_value

# In production, encryption is automatic when LOG_FERNET_KEY is set
symbol = "BTCUSDT"
encrypted = encrypt_value(symbol)  # Fernet ciphertext
logger.info("Symbol encrypted", extra={"symbol_encrypted": encrypted})

# Later, with the key, decrypt for auditing
decrypted = decrypt_value(encrypted)
assert decrypted == symbol
```

**Log Output:**
```json
{
  "ts": "2026-08-17T22:30:56.637Z",
  "level": "INFO",
  "msg": "Symbol encrypted",
  "symbol_encrypted": "gAAAAABk2...truncated...Xa9Yq8="
}
```

---

## Configuration Patterns

### Development Configuration

```python
# main.py (development)
import os
from logging.logging_config import load_from_dict_config
from logging.logging_example_config import LOGGING_CONFIG_DEVELOPMENT

os.environ.setdefault("LOG_LEVEL", "DEBUG")
load_from_dict_config(LOGGING_CONFIG_DEVELOPMENT)
```

### Production Configuration

```python
# main.py (production)
import os
from logging.logging_config import load_from_dict_config
from logging.logging_example_config import LOGGING_CONFIG_PRODUCTION

os.environ.setdefault("LOG_LEVEL", "INFO")
load_from_dict_config(LOGGING_CONFIG_PRODUCTION)
```

### Custom Configuration with File Logging

```python
# custom_logging_config.py
CUSTOM_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": "app.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
        },
    },
    "root": {
        "level": "$(LOG_LEVEL)",
        "handlers": ["console", "file"],
    },
}

# main.py
from logging.logging_config import load_from_dict_config
from custom_logging_config import CUSTOM_CONFIG

load_from_dict_config(CUSTOM_CONFIG)
```

---

## Testing

### Unit Test with Correlation IDs

```python
# test_trade_processor.py
import pytest
from services.market_data.processor import TradeProcessor
from logging.logging_filter import set_correlation_id


class TestTradeProcessor:
    @pytest.fixture(autouse=True)
    def setup(self):
        set_correlation_id("test_12345")
        yield
        set_correlation_id(None)

    async def test_process_trade(self):
        processor = TradeProcessor()
        result = await processor.process_trade({"s": "BTCUSDT", "p": "45000"})
        assert result.symbol == "BTCUSDT"
```

### Testing Redaction

```python
# test_logging_redaction.py
from services.logging_helpers import redact_payload, redact_symbol


def test_redact_symbol():
    assert redact_symbol("BTCUSDT") == redact_symbol("btcusdt")
    assert redact_symbol("BTCUSDT").startswith("sym_")


def test_redact_payload():
    data = {
        "symbol": "BTCUSDT",
        "api_key": "sk_123",
        "price": 45000,
        "nested": {"token": "secret"}
    }
    redacted = redact_payload(data)

    assert "BTCUSDT" not in str(redacted)
    assert "sk_123" not in str(redacted)
    assert redacted["price"] == 45000  # Non-sensitive preserved
    assert "<redacted" in redacted["api_key"]
    assert "<redacted" in redacted["nested"]["token"]
```

### Testing Encryption

```python
# test_logging_encryption.py
from logging.logging_crypto import encrypt_value, decrypt_value, _parse_fernet_key
import os


def test_encryption_roundtrip(monkeypatch):
    # Set Fernet key for test
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    monkeypatch.setenv("LOG_FERNET_KEY", key.decode("utf-8"))

    # Reload to pick up new key
    import importlib
    import logging.logging_crypto
    importlib.reload(logging.logging_crypto)

    original = "BTCUSDT"
    encrypted = logging.logging_crypto.encrypt_value(original)
    decrypted = logging.logging_crypto.decrypt_value(encrypted)

    assert decrypted == original
```

### Testing Key Parsing

```python
# test_logging_crypto.py (covered by services/tests_logging_crypto.py)
from logging.logging_crypto import _parse_fernet_key, _parse_hmac_key
import base64


def test_parse_fernet_key_from_hex():
    raw_32 = os.urandom(32)
    hex_str = raw_32.hex()
    result = _parse_fernet_key(hex_str)

    assert result is not None
    decoded = base64.urlsafe_b64decode(result)
    assert decoded == raw_32


def test_parse_hmac_key_from_base64():
    raw = b"my-secret-key-here"
    b64 = base64.b64encode(raw).decode("utf-8")
    result = _parse_hmac_key(b64)

    assert result == raw
```

---

## Performance Considerations

### Queue Handler Benefits

```python
# Async-safe non-blocking logging
configure_app_logging()  # Uses QueueHandler by default

# Critical path unblocked
async def process_trades():
    for trade in trades:
        logger.info("Trade", extra={"symbol": trade.symbol})  # Non-blocking
        await process(trade)  # Logging doesn't slow down processing
```

### Disabling Queue Handler (Not Recommended)

```python
import os

os.environ["LOG_USE_QUEUE"] = "false"
from logging.logging_config import configure_app_logging

configure_app_logging()  # Direct logging (blocking)
```

---

## Troubleshooting

### No Logs Appearing

```bash
# Check LOG_LEVEL
export LOG_LEVEL=DEBUG
python app.py

# Verify logger level
logger = logging.getLogger("my_module")
print(f"Logger level: {logger.level}, Effective level: {logger.getEffectiveLevel()}")
```

### Fernet Key Invalid

```bash
# Key must be 32 bytes in base64 or hex format
# Valid: 44-char base64 or 64-char hex

# Generate valid key
python -c "from services.logging_crypto import generate_fernet_key; print(generate_fernet_key())"
```

### Redaction Not Working

```python
# Ensure RedactionFilter is attached to handlers
handler.addFilter(RedactionFilter())

# Verify sensitive keys are in DEFAULT_SENSITIVE_KEYS
from services.logging_helpers import DEFAULT_SENSITIVE_KEYS

print(DEFAULT_SENSITIVE_KEYS)  # {"s", "symbol", "secret", "token", "api_key", "password", "account"}

# Add custom keys if needed
redact_payload(data, keys_to_mask={"custom_field", "another_field"})
```

---

## References

- [Python Logging Documentation](https://docs.python.org/3/library/logging.html)
- [python-json-logger](https://github.com/madzak/python-json-logger)
- [Cryptography Fernet](https://cryptography.io/en/latest/fernet/)
- [Contextvars Documentation](https://docs.python.org/3/library/contextvars.html)
