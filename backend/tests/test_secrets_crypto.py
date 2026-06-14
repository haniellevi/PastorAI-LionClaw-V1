"""Tests for secret encryption (RNF-03) and sensitive-data masking (F8)."""

from __future__ import annotations

import os

import pytest

from app.agent import masking
from app.config import get_settings
from app.services import crypto


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    """Configure an encryption key and reset the cached settings/fernet."""
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "uma-passphrase-de-teste")
    get_settings.cache_clear()
    crypto._get_fernet.cache_clear()
    yield
    get_settings.cache_clear()
    crypto._get_fernet.cache_clear()


def test_encrypt_decrypt_roundtrip() -> None:
    token = crypto.encrypt_secret("sk-super-secret-key")
    assert token != "sk-super-secret-key"
    assert "sk-super-secret-key" not in token  # never stored in clear (RNF-03)
    assert crypto.decrypt_secret(token) == "sk-super-secret-key"


def test_encrypt_is_non_deterministic() -> None:
    a = crypto.encrypt_secret("same-value")
    b = crypto.encrypt_secret("same-value")
    assert a != b  # Fernet uses a random IV/timestamp
    assert crypto.decrypt_secret(a) == crypto.decrypt_secret(b) == "same-value"


def test_decrypt_tampered_token_raises() -> None:
    token = crypto.encrypt_secret("value")
    with pytest.raises(crypto.SecretDecryptionError):
        crypto.decrypt_secret(token[:-4] + "AAAA")


def test_missing_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    crypto._get_fernet.cache_clear()
    with pytest.raises(crypto.SecretsConfigError):
        crypto.encrypt_secret("x")


def test_mask_text_redacts_cpf_email_and_digits() -> None:
    masked = masking.mask_text("CPF 123.456.789-09, fone 11999998888, e a@b.com")
    assert "123.456.789-09" not in masked
    assert "11999998888" not in masked
    assert "a@b.com" not in masked
    assert "***" in masked


def test_mask_payload_is_recursive() -> None:
    payload = {"nota": "cpf 123.456.789-09", "lista": ["email x@y.com"], "n": 3}
    masked = masking.mask_payload(payload)
    assert "123.456.789-09" not in masked["nota"]
    assert "x@y.com" not in masked["lista"][0]
    assert masked["n"] == 3  # non-strings untouched
