class TestSecretEncryption:
    """Newsletter credentials remain encrypted at rest."""

    def test_roundtrip(self):
        from empulse.crypto import decrypt_secret, encrypt_secret

        encrypted = encrypt_secret("hunter2")
        assert encrypted != "hunter2"
        assert encrypted.startswith("enc:v1:")
        assert decrypt_secret(encrypted) == "hunter2"

    def test_empty_value_passes_through(self):
        from empulse.crypto import decrypt_secret, encrypt_secret

        assert encrypt_secret("") == ""
        assert encrypt_secret(None) == ""
        assert decrypt_secret("") == ""

    def test_legacy_plaintext_passes_through_unchanged(self):
        from empulse.crypto import decrypt_secret

        # Value without the enc:v1: prefix is treated as pre-migration plaintext.
        assert decrypt_secret("plain-old-secret") == "plain-old-secret"

    def test_undecryptable_token_fails_closed(self):
        # A valid enc:v1: token that can't be decrypted (e.g. after SECRET_KEY
        # rotation) must return "" — never the ciphertext, which would leak
        # enc:v1:… as the literal SMTP credential.
        from empulse.crypto import decrypt_secret

        bogus = "enc:v1:gAAAAABmnot-a-real-token"
        assert decrypt_secret(bogus) == ""

    def test_encrypt_is_idempotent(self):
        from empulse.crypto import encrypt_secret

        once = encrypt_secret("hunter2")
        twice = encrypt_secret(once)
        assert once == twice


def test_decrypts_password_from_before_channel_removal(monkeypatch):
    from empulse import crypto

    monkeypatch.setattr(crypto.settings, "secret_key", "legacy-test-secret")
    monkeypatch.setattr(crypto, "_fernet", None)
    stored = (
        "enc:v1:gAAAAABqnUz5o2F7fnKLJsHzzLtxxrat8a5RN9kQcVPIyKgZ_WCJwFCNujmI"
        "OXoPyHXL4_SbEpE_Fm__8WSBMl16N6x63ee_nfMrUPf_8o-91_AFoJyeJVQ="
    )
    assert crypto.decrypt_secret(stored) == "legacy-smtp-password"
