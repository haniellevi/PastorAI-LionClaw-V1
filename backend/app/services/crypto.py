"""Symmetric encryption for secrets at rest (RNF-03 / US-27).

BYO-LLM API keys are persisted encrypted in `llm_credentials.api_key_encrypted`
and never returned in clear text after being saved. Encryption uses Fernet
(AES-128-CBC + HMAC-SHA256, authenticated) from the `cryptography` package
(already a transitive dependency of PyJWT[crypto]).

The key comes from `SECRETS_ENCRYPTION_KEY`. To be forgiving about the exact
format configured by operators, we accept either:
  - a valid 32-byte url-safe base64 Fernet key (used directly), or
  - any other non-empty secret, from which a deterministic Fernet key is
    derived via SHA-256 (so a passphrase also works).

A missing key is a hard error: we never store a secret unencrypted.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretsConfigError(RuntimeError):
    """Raised when the encryption key is missing or unusable."""


class SecretDecryptionError(RuntimeError):
    """Raised when a stored ciphertext cannot be decrypted (tampering/rotation)."""


def _derive_fernet_key(raw: str) -> bytes:
    """Coerce the configured secret into a valid Fernet key.

    A correctly-sized url-safe base64 key is used as-is; anything else is
    hashed (SHA-256) and re-encoded so any passphrase yields a usable key.
    """
    candidate = raw.strip().encode("utf-8")
    try:
        # Fernet keys are 32 url-safe base64 bytes (44 chars incl. padding).
        if len(base64.urlsafe_b64decode(candidate)) == 32:
            return candidate
    except (ValueError, TypeError):
        pass
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache
def _get_fernet() -> Fernet:
    settings = get_settings()
    if not settings.secrets_encryption_key:
        raise SecretsConfigError(
            "SECRETS_ENCRYPTION_KEY não configurada; não é possível cifrar segredos"
        )
    return Fernet(_derive_fernet_key(settings.secrets_encryption_key))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret, returning a url-safe base64 token (str)."""
    if not plaintext:
        raise ValueError("Não é possível cifrar um segredo vazio")
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret`."""
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretDecryptionError("Falha ao decifrar segredo armazenado") from exc
