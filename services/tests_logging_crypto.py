"""Unit tests for logging_crypto module (HMAC/Fernet key parsing and encryption)."""
import base64
import os
from cryptography.fernet import Fernet

from services.logging_crypto import (
    _parse_hmac_key,
    _parse_fernet_key,
    deterministic_id,
    encrypt_value,
    decrypt_value,
    generate_fernet_key,
    generate_hmac_key,
)


class TestParseHmacKey:
    """Test HMAC key parsing from various formats."""

    def test_parse_base64_encoded_key(self):
        """Valid base64-encoded key should be decoded."""
        raw = b"test-hmac-key-32-bytes-long!!!"
        b64 = base64.b64encode(raw)
        result = _parse_hmac_key(b64.decode("utf-8"))
        assert result == raw

    def test_parse_hex_encoded_key(self):
        """Valid hex-encoded key should be decoded."""
        raw = b"test-key"
        hex_str = raw.hex()
        result = _parse_hmac_key(hex_str)
        assert result == raw

    def test_parse_raw_string_key(self):
        """Raw string key should be UTF-8 encoded."""
        key_str = "my-secret-key"
        result = _parse_hmac_key(key_str)
        assert result == key_str.encode("utf-8")

    def test_parse_empty_string_returns_none(self):
        """Empty string should return None."""
        result = _parse_hmac_key("")
        assert result is None

    def test_parse_none_returns_none(self):
        """None input should return None."""
        result = _parse_hmac_key(None)
        assert result is None

    def test_parse_invalid_base64_falls_back(self):
        """Invalid base64 should fall back to utf-8 encoding."""
        invalid_b64 = "!!!invalid-base64!!!"
        result = _parse_hmac_key(invalid_b64)
        # Should fall back to UTF-8 encoding
        assert result == invalid_b64.encode("utf-8")

    def test_parse_mixed_valid_formats(self):
        """Should try base64 first, then hex, then raw."""
        # This is valid base64 AND valid hex, so base64 should win
        b64_str = base64.b64encode(b"test").decode("utf-8")
        result = _parse_hmac_key(b64_str)
        assert result == b"test"


class TestParseFernetKey:
    """Test Fernet key parsing from various formats."""

    def test_parse_valid_fernet_key(self):
        """Valid Fernet key (base64) should be returned as bytes."""
        valid_key = Fernet.generate_key()  # Returns base64-encoded bytes
        result = _parse_fernet_key(valid_key.decode("utf-8"))
        assert result == valid_key  # Should return bytes

    def test_parse_32_byte_hex_key(self):
        """32-byte hex key should be converted to base64."""
        raw_32 = os.urandom(32)
        hex_str = raw_32.hex()
        result = _parse_fernet_key(hex_str)
        # Should return base64-encoded version
        assert result is not None
        decoded = base64.urlsafe_b64decode(result)
        assert decoded == raw_32

    def test_parse_32_byte_raw_string(self):
        """32-character raw string should be converted to base64."""
        raw_str = "a" * 32  # Exactly 32 chars
        result = _parse_fernet_key(raw_str)
        assert result is not None
        decoded = base64.urlsafe_b64decode(result)
        assert decoded == raw_str.encode("utf-8")

    def test_parse_empty_string_returns_none(self):
        """Empty string should return None."""
        result = _parse_fernet_key("")
        assert result is None

    def test_parse_none_returns_none(self):
        """None input should return None."""
        result = _parse_fernet_key(None)
        assert result is None

    def test_parse_invalid_key_returns_none(self):
        """Invalid key (not 32 bytes in any format) should return None."""
        invalid = "too-short"
        result = _parse_fernet_key(invalid)
        assert result is None

    def test_parse_wrong_size_hex_returns_none(self):
        """Hex string not representing 32 bytes should return None."""
        wrong_size_hex = "abcd" * 10  # 40 bytes, not 32
        result = _parse_fernet_key(wrong_size_hex)
        assert result is None


class TestDeterministicId:
    """Test deterministic ID generation."""

    def test_deterministic_id_default_length(self):
        """Should return 'sym_' prefix + 8 hex chars."""
        result = deterministic_id("BTCUSDT")
        assert result.startswith("sym_")
        assert len(result) == 12  # "sym_" (4) + 8 hex chars

    def test_deterministic_id_custom_length(self):
        """Should respect custom length parameter."""
        result = deterministic_id("BTCUSDT", length=4)
        assert result.startswith("sym_")
        assert len(result) == 8  # "sym_" (4) + 4 hex chars

    def test_deterministic_id_consistency(self):
        """Same input should produce same output (deterministic)."""
        id1 = deterministic_id("BTCUSDT")
        id2 = deterministic_id("BTCUSDT")
        assert id1 == id2

    def test_deterministic_id_case_insensitive(self):
        """Should normalize to uppercase for consistent hashing."""
        id_upper = deterministic_id("BTCUSDT")
        id_lower = deterministic_id("btcusdt")
        assert id_upper == id_lower

    def test_deterministic_id_empty_returns_none(self):
        """Empty/None symbol should return '<none>'."""
        assert deterministic_id("") == "<none>"
        assert deterministic_id(None) == "<none>"

    def test_deterministic_id_different_inputs(self):
        """Different inputs should produce different outputs."""
        id1 = deterministic_id("BTCUSDT")
        id2 = deterministic_id("ETHUSDT")
        assert id1 != id2


class TestFernetEncryption:
    """Test reversible encryption with Fernet."""

    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        """Encrypt then decrypt should return original value."""
        # Temporarily set the env var and reload the module
        key = Fernet.generate_key()
        monkeypatch.setenv("LOG_FERNET_KEY", key.decode("utf-8"))
        
        original = "BTCUSDT"
        encrypted = encrypt_value(original)
        assert encrypted is not None
        assert encrypted != original

        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_encrypt_without_key_returns_none(self, monkeypatch):
        """Without Fernet key, encryption should return None."""
        monkeypatch.delenv("LOG_FERNET_KEY", raising=False)
        result = encrypt_value("BTCUSDT")
        # Will return None if key not set
        assert result is None

    def test_encrypt_empty_returns_none(self):
        """Empty value should return None."""
        assert encrypt_value("") is None
        assert encrypt_value(None) is None

    def test_decrypt_invalid_token_returns_none(self):
        """Invalid token should return None."""
        result = decrypt_value("invalid-token")
        assert result is None

    def test_decrypt_empty_returns_none(self):
        """Empty token should return None."""
        assert decrypt_value("") is None
        assert decrypt_value(None) is None


class TestKeyGeneration:
    """Test key generation helpers."""

    def test_generate_fernet_key_valid(self):
        """Generated Fernet key should be valid."""
        key_str = generate_fernet_key()
        assert isinstance(key_str, str)
        # Should be valid base64
        decoded = base64.urlsafe_b64decode(key_str)
        assert len(decoded) == 32  # Fernet requires 32-byte keys

    def test_generate_hmac_key_valid(self):
        """Generated HMAC key should be valid base64."""
        key_str = generate_hmac_key()
        assert isinstance(key_str, str)
        # Should be valid base64
        decoded = base64.b64decode(key_str)
        assert len(decoded) == 32

    def test_generate_keys_are_random(self):
        """Generated keys should be different each time."""
        key1 = generate_fernet_key()
        key2 = generate_fernet_key()
        assert key1 != key2

        hmac1 = generate_hmac_key()
        hmac2 = generate_hmac_key()
        assert hmac1 != hmac2
