"""Shared definitions + helpers for encrypting/decrypting notification channel
secrets at rest. Used by both the API layer (write path) and the notification
engine (read path, right before dispatch) so the field list lives in one place.
"""

import json

from empulse.crypto import decrypt_secret, encrypt_secret

MASKED_SECRET = "***"

# Per channel_type, the config fields that hold sensitive values and should
# be encrypted at rest / masked in API responses.
CHANNEL_SECRET_FIELDS = {
    "discord": {"url"},
    "webhook": {"url", "headers"},
    "email": {"smtp_pass"},
    "telegram": {"bot_token"},
    "ntfy": {"auth"},
}

# "headers" is stored as a dict/list rather than a plain string.
_JSON_FIELDS = {"headers"}


def encrypt_channel_config(channel_type: str, config: dict) -> dict:
    """Encrypt secret fields in a channel config before writing to the DB."""
    encrypted = dict(config)
    for field in CHANNEL_SECRET_FIELDS.get(channel_type, set()):
        value = encrypted.get(field)
        if not value:
            continue
        raw = json.dumps(value) if field in _JSON_FIELDS else str(value)
        encrypted[field] = encrypt_secret(raw)
    return encrypted


def decrypt_channel_config(channel_type: str, config: dict) -> dict:
    """Decrypt secret fields in a channel config for actual use (sending)."""
    decrypted = dict(config)
    for field in CHANNEL_SECRET_FIELDS.get(channel_type, set()):
        value = decrypted.get(field)
        if not value or not isinstance(value, str):
            continue
        plain = decrypt_secret(value)
        if field in _JSON_FIELDS:
            try:
                decrypted[field] = json.loads(plain) if plain else {}
            except (json.JSONDecodeError, TypeError):
                decrypted[field] = {}
        else:
            decrypted[field] = plain
    return decrypted
