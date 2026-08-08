"""Encryption helpers for secrets stored at rest (notification channel
credentials, newsletter SMTP password).

The Fernet key is derived from `settings.secret_key` via HKDF-SHA256, so no
separate key management is required — rotating `SECRET_KEY` rotates this key
too (and invalidates previously-encrypted values; see README for details).
"""

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from empulse.config import settings

logger = logging.getLogger("empulse.crypto")

ENC_PREFIX = "enc:v1:"

_fernet: Fernet | None = None


def _derive_key(secret_key: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"empulse:channel")
    raw = hkdf.derive(secret_key.encode())
    return base64.urlsafe_b64encode(raw)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_key(settings.secret_key))
    return _fernet


def encrypt_secret(value: str | None) -> str:
    """Encrypt a secret value for storage. Empty/None values pass through
    unchanged (nothing to encrypt), and already-encrypted values are left
    as-is (idempotent)."""
    if not value:
        return value or ""
    if value.startswith(ENC_PREFIX):
        return value
    token = _get_fernet().encrypt(value.encode()).decode()
    return ENC_PREFIX + token


def decrypt_secret(value: str | None) -> str:
    """Decrypt a stored secret value. Values without the enc:v1: prefix are
    treated as legacy plaintext (pre-migration) and returned unchanged."""
    if not value:
        return value or ""
    if not value.startswith(ENC_PREFIX):
        return value
    token = value[len(ENC_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # Fail closed: never hand back the ciphertext, or a SECRET_KEY rotation
        # would leak enc:v1:… as the literal credential to the channel.
        logger.warning("Failed to decrypt a stored secret (invalid token) — returning empty")
        return ""
