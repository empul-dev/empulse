import json
import pytest
import pytest_asyncio
import aiosqlite

from empulse.database import SCHEMA
from empulse.notifications.engine import NotificationEngine
from empulse.web.api import _redact_channel, _preserve_channel_secrets


@pytest_asyncio.fixture
async def db():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def engine(db):
    eng = NotificationEngine(lambda: db)
    return eng


class TestNotificationEngine:
    @pytest.mark.asyncio
    async def test_emit_no_channels(self, engine):
        """Emit with no channels configured should not error."""
        await engine.emit("playback_start", {"user_name": "Test", "item_name": "Movie"})

    @pytest.mark.asyncio
    async def test_condition_user_filter(self, engine):
        assert engine._check_conditions(
            {"conditions": json.dumps({"users": ["u1"]})},
            {"user_id": "u1"},
        )
        assert not engine._check_conditions(
            {"conditions": json.dumps({"users": ["u1"]})},
            {"user_id": "u2"},
        )

    @pytest.mark.asyncio
    async def test_condition_type_filter(self, engine):
        assert engine._check_conditions(
            {"conditions": json.dumps({"types": ["Movie"]})},
            {"item_type": "Movie"},
        )
        assert not engine._check_conditions(
            {"conditions": json.dumps({"types": ["Movie"]})},
            {"item_type": "Episode"},
        )

    @pytest.mark.asyncio
    async def test_condition_min_duration(self, engine):
        assert engine._check_conditions(
            {"conditions": json.dumps({"min_duration": 60})},
            {"duration_seconds": 120},
        )
        assert not engine._check_conditions(
            {"conditions": json.dumps({"min_duration": 60})},
            {"duration_seconds": 30},
        )

    @pytest.mark.asyncio
    async def test_condition_empty(self, engine):
        assert engine._check_conditions({"conditions": "{}"}, {"user_id": "u1"})

    @pytest.mark.asyncio
    async def test_build_summary(self, engine):
        summary = engine._build_summary("playback_start", {
            "user_name": "Alice",
            "item_name": "Test Movie",
        })
        assert "Alice" in summary
        assert "started" in summary
        assert "Test Movie" in summary

    @pytest.mark.asyncio
    async def test_build_summary_series(self, engine):
        summary = engine._build_summary("watched", {
            "user_name": "Bob",
            "item_name": "Pilot",
            "series_name": "Test Show",
        })
        assert "Bob" in summary
        assert "watched" in summary
        assert "Test Show - Pilot" in summary

    @pytest.mark.asyncio
    async def test_log_entry(self, db, engine):
        await engine._log(1, "playback_start", "Alice started Movie", "sent", None)
        cursor = await db.execute("SELECT * FROM notification_log")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["event_type"] == "playback_start"
        assert dict(rows[0])["status"] == "sent"

    @pytest.mark.asyncio
    async def test_log_failed(self, db, engine):
        await engine._log(1, "playback_stop", "Bob stopped Movie", "failed", "timeout")
        cursor = await db.execute("SELECT * FROM notification_log")
        rows = await cursor.fetchall()
        assert dict(rows[0])["status"] == "failed"
        assert dict(rows[0])["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, db, engine):
        from datetime import datetime, timezone

        # Insert two channels
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO notification_channels (name, channel_type, config, triggers, conditions, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["First", "webhook", '{"url":"http://example.com"}', '["playback_start"]', '{}', 1, now],
        )
        await db.commit()

        # Load — should find 1 channel
        channels = await engine._load_channels()
        assert len(channels) == 1
        assert channels[0]["name"] == "First"

        # Insert another channel — cache still returns 1
        await db.execute(
            "INSERT INTO notification_channels (name, channel_type, config, triggers, conditions, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["Second", "webhook", '{"url":"http://example2.com"}', '["playback_stop"]', '{}', 1, now],
        )
        await db.commit()

        # Still cached
        channels = await engine._load_channels()
        assert len(channels) == 1

        # Invalidate and reload
        engine.invalidate_cache()
        channels = await engine._load_channels()
        assert len(channels) == 2


class TestNewMedia:
    @pytest.mark.asyncio
    async def test_build_summary_single(self, engine):
        summary = engine._build_summary("new_media", {"item_name": "Some Movie"})
        assert summary == "New: Some Movie"
        assert "Unknown" not in summary

    @pytest.mark.asyncio
    async def test_build_summary_batch(self, engine):
        summary = engine._build_summary(
            "new_media", {"item_name": "37 new items added", "item_type": "Batch"}
        )
        assert summary == "New: 37 new items added"
        assert "Unknown" not in summary

    def test_select_new_items_drops_stale(self):
        from empulse.emby.websocket import _select_new_items
        from datetime import datetime, timezone

        now = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)
        items = [
            {"Id": "1", "Name": "Fresh", "Type": "Movie",
             "DateCreated": "2026-08-08T11:59:00.0000000Z"},
            {"Id": "2", "Name": "Rescanned", "Type": "Movie",
             "DateCreated": "2020-01-01T00:00:00.0000000Z"},
            {"Id": "3", "Name": "Season folder", "Type": "Season",
             "DateCreated": "2026-08-08T11:59:00.0000000Z"},
        ]
        events = _select_new_items(items, now, max_age_minutes=120, cap=20)
        assert len(events) == 1
        assert events[0]["item_name"] == "Fresh"

    def test_select_new_items_aggregates_over_cap(self):
        from empulse.emby.websocket import _select_new_items
        from datetime import datetime, timezone

        now = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)
        items = [
            {"Id": str(i), "Name": f"M{i}", "Type": "Movie",
             "DateCreated": "2026-08-08T11:59:00.0000000Z"}
            for i in range(5)
        ]
        events = _select_new_items(items, now, max_age_minutes=120, cap=2)
        assert events == [{"item_name": "5 new items added", "item_type": "Batch"}]


class TestNotificationSecretHandling:
    def test_redact_channel_masks_secret_config_fields(self):
        channel = {
            "id": 1,
            "channel_type": "telegram",
            "config": {"bot_token": "secret-token", "chat_id": "123"},
        }
        redacted = _redact_channel(channel)
        assert redacted["config"]["bot_token"] == "***"
        assert redacted["config"]["chat_id"] == "123"

    def test_preserve_channel_secrets_keeps_masked_values(self):
        merged = _preserve_channel_secrets(
            "webhook",
            {"url": "***", "headers": "***", "method": "POST"},
            {"url": "https://example.com/hook", "headers": {"Authorization": "Bearer token"}},
        )
        assert merged["url"] == "https://example.com/hook"
        assert merged["headers"] == {"Authorization": "Bearer token"}
        assert merged["method"] == "POST"


class TestSecretEncryption:
    """I-1: notification channel / newsletter secrets are encrypted at rest."""

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
        # enc:v1:… as the literal credential to the channel.
        from empulse.crypto import decrypt_secret

        bogus = "enc:v1:gAAAAABmnot-a-real-token"
        assert decrypt_secret(bogus) == ""

    def test_encrypt_is_idempotent(self):
        from empulse.crypto import encrypt_secret

        once = encrypt_secret("hunter2")
        twice = encrypt_secret(once)
        assert once == twice

    def test_encrypt_decrypt_channel_config_roundtrip(self):
        from empulse.notifications.secrets import (
            decrypt_channel_config,
            encrypt_channel_config,
        )

        config = {"bot_token": "abc123", "chat_id": "999"}
        encrypted = encrypt_channel_config("telegram", config)
        assert encrypted["bot_token"] != "abc123"
        assert encrypted["bot_token"].startswith("enc:v1:")
        assert encrypted["chat_id"] == "999"  # non-secret field untouched

        decrypted = decrypt_channel_config("telegram", encrypted)
        assert decrypted["bot_token"] == "abc123"

    def test_encrypt_decrypt_webhook_headers_dict(self):
        from empulse.notifications.secrets import (
            decrypt_channel_config,
            encrypt_channel_config,
        )

        config = {
            "url": "https://example.com/hook",
            "headers": {"Authorization": "Bearer secret-token"},
            "method": "POST",
        }
        encrypted = encrypt_channel_config("webhook", config)
        assert isinstance(encrypted["headers"], str)
        assert "secret-token" not in encrypted["headers"]
        assert encrypted["method"] == "POST"

        decrypted = decrypt_channel_config("webhook", encrypted)
        assert decrypted["headers"] == {"Authorization": "Bearer secret-token"}

    @pytest.mark.asyncio
    async def test_created_channel_stores_encrypted_secret_in_db(self, db):
        """End-to-end through the API write path."""
        from unittest.mock import AsyncMock, patch

        from empulse.app import create_app

        with (
            patch("empulse.app.init_db", new_callable=AsyncMock),
            patch("empulse.app.settings") as mock_settings,
        ):
            mock_settings.emby_api_key = ""
            mock_settings.emby_url = "http://localhost:8096"
            mock_settings.auth_password = "testpass"
            mock_settings.secret_key = "testsecret"
            mock_settings.disable_update_check = True
            mock_settings.update_check_interval = 43200

            app = create_app()

        from datetime import datetime, timedelta, timezone

        from empulse.web.auth import (
            COOKIE_NAME,
            SESSION_MAX_AGE,
            create_session_token,
            hash_token,
        )

        token = create_session_token("testsecret", "__admin__", "admin")
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=SESSION_MAX_AGE)
        await db.execute(
            "INSERT INTO login_sessions (token_hash, emby_user_id, username, role, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [hash_token(token), None, "TestAdmin", "admin", now.isoformat(), expires.isoformat()],
        )
        await db.commit()

        from httpx import ASGITransport, AsyncClient

        with (
            patch("empulse.web.router.get_db", return_value=db),
            patch("empulse.web.api.get_db", return_value=db),
            patch("empulse.database.get_db", return_value=db),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test", headers={"Origin": "http://test"}
            ) as ac:
                ac.cookies.set(COOKIE_NAME, token)
                r = await ac.post(
                    "/api/notification-channels",
                    json={
                        "name": "My Telegram",
                        "channel_type": "telegram",
                        "config": {"bot_token": "abc123", "chat_id": "999"},
                        "triggers": ["playback_start"],
                        "enabled": True,
                    },
                )
                assert r.status_code == 201

        cursor = await db.execute("SELECT config FROM notification_channels")
        row = await cursor.fetchone()
        stored_config = json.loads(row["config"])
        assert stored_config["bot_token"].startswith("enc:v1:")
        assert "abc123" not in row["config"]


class TestNotificationRedaction:
    """I-3: notification failure messages don't leak secrets into logs."""

    def test_scrub_query_param_tokens(self):
        from empulse.notifications._redact import scrub

        text = "Request to https://example.com/hook?token=abc123&user=bob failed"
        scrubbed = scrub(text)
        assert "abc123" not in scrubbed
        assert "token=***" in scrubbed

    def test_scrub_telegram_bot_token(self):
        from empulse.notifications._redact import scrub

        text = "POST https://api.telegram.org/bot123456:AAFsecretvalue/sendMessage failed"
        scrubbed = scrub(text)
        assert "AAFsecretvalue" not in scrubbed

    def test_scrub_discord_webhook_token(self):
        from empulse.notifications._redact import scrub

        text = "https://discord.com/api/webhooks/123456789/superSecretToken failed with 401"
        scrubbed = scrub(text)
        assert "superSecretToken" not in scrubbed

    @pytest.mark.asyncio
    async def test_dispatch_failure_log_is_scrubbed(self, db, engine, caplog):
        import logging

        channel = {
            "id": 1,
            "name": "Bad Webhook",
            "channel_type": "webhook",
            "config": json.dumps({"url": "https://example.com/hook?token=leak-me-1234"}),
        }
        with (
            caplog.at_level(logging.ERROR, logger="empulse.notifications"),
            pytest.MonkeyPatch.context() as mp,
        ):
            async def _boom(*a, **k):
                raise ValueError("failed for url https://example.com/hook?token=leak-me-1234")

            from empulse.notifications.channels import webhook as webhook_mod
            mp.setattr(webhook_mod, "send_webhook", _boom)

            await engine._dispatch(channel, "playback_start", {"user_name": "Alice", "item_name": "Movie"})

        assert "leak-me-1234" not in caplog.text

        cursor = await db.execute("SELECT error FROM notification_log")
        row = await cursor.fetchone()
        assert "leak-me-1234" not in (row["error"] or "")


class TestWebhookTemplate:
    def test_apply_template(self):
        from empulse.notifications.channels.webhook import _apply_template
        result = _apply_template(
            '{"event": "{event}", "user": "{user}", "title": "{title}"}',
            "playback_start",
            {"user_name": "Alice", "item_name": "Movie"},
        )
        parsed = json.loads(result)
        assert parsed["event"] == "playback_start"
        assert parsed["user"] == "Alice"
        assert parsed["title"] == "Movie"

    def test_user_controlled_value_cannot_expand_placeholder(self):
        # E-5: a username of "{ip}" must NOT expand into the real IP.
        from empulse.notifications.channels.webhook import _apply_template
        result = _apply_template(
            "{user} watched from {ip}",
            "playback_start",
            {"user_name": "{ip}", "ip_address": "10.0.0.9"},
        )
        assert result == "{ip} watched from 10.0.0.9"

    def test_json_mode_escapes_quotes(self):
        # E-5: a value with a quote must not break out of its JSON string.
        from empulse.notifications.channels.webhook import _apply_template
        result = _apply_template(
            '{"user": "{user}"}',
            "playback_start",
            {"user_name": 'evil", "admin": true, "x": "'},
            json_mode=True,
        )
        parsed = json.loads(result)
        assert set(parsed) == {"user"}
        assert parsed["user"] == 'evil", "admin": true, "x": "'


class TestEmailChannel:
    def test_build_plain(self):
        from empulse.notifications.channels.email import _build_plain
        result = _build_plain("playback_start", {
            "user_name": "Alice",
            "item_name": "Test Movie",
            "play_method": "DirectPlay",
            "client": "Web",
            "device_name": "Chrome",
            "duration_seconds": 3700,
            "percent_complete": 75.0,
        })
        assert "Alice" in result
        assert "Test Movie" in result
        assert "DirectPlay" in result
        assert "75%" in result

    def test_build_html(self):
        from empulse.notifications.channels.email import _build_html
        result = _build_html("watched", {
            "user_name": "Bob",
            "item_name": "Pilot",
            "series_name": "Show",
        })
        assert "<html>" in result
        assert "Bob" in result
        assert "Show - Pilot" in result


class TestTelegramChannel:
    def test_build_message(self):
        from empulse.notifications.channels.telegram import _build_message
        result = _build_message("playback_start", {
            "user_name": "Alice",
            "item_name": "Test Movie",
            "play_method": "DirectPlay",
        })
        assert "Alice" in result
        assert "Test Movie" in result
        assert "Playback Started" in result

    def test_escape(self):
        from empulse.notifications.channels.telegram import _escape
        assert _escape("hello_world") == "hello\\_world"
        assert _escape("a*b") == "a\\*b"


class TestNtfyChannel:
    @pytest.mark.asyncio
    async def test_send_ntfy_no_topic(self):
        from empulse.notifications.channels.ntfy import send_ntfy
        with pytest.raises(ValueError, match="topic"):
            await send_ntfy({}, "playback_start", {"user_name": "Test"})


class TestNewsletter:
    @pytest.mark.asyncio
    async def test_config_crud(self, db):
        from empulse.newsletter import get_newsletter_config, save_newsletter_config
        # Initially empty
        config = await get_newsletter_config(db)
        assert config is None

        # Save
        await save_newsletter_config(db, {
            "enabled": True,
            "schedule": "weekly",
            "day_of_week": 1,
            "hour": 10,
            "recently_added_days": 7,
            "recently_added_limit": 20,
            "include_stats": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "smtp_pass": "pass",
            "smtp_tls": True,
            "from_addr": "from@example.com",
            "to_addrs": "to@example.com",
        })

        config = await get_newsletter_config(db)
        assert config is not None
        assert config["enabled"] == 1
        assert config["schedule"] == "weekly"

        # Update
        await save_newsletter_config(db, {
            "enabled": False,
            "schedule": "daily",
            "day_of_week": 0,
            "hour": 8,
            "recently_added_days": 3,
            "recently_added_limit": 10,
            "include_stats": False,
            "smtp_host": "mail.example.com",
            "smtp_port": 465,
            "smtp_user": "",
            "smtp_pass": "",
            "smtp_tls": False,
            "from_addr": "",
            "to_addrs": "",
        })
        config = await get_newsletter_config(db)
        assert config["schedule"] == "daily"
        assert config["enabled"] == 0

    @pytest.mark.asyncio
    async def test_config_preserves_masked_password(self, db):
        from empulse.newsletter import get_newsletter_config, save_newsletter_config

        await save_newsletter_config(db, {
            "enabled": True,
            "schedule": "weekly",
            "day_of_week": 1,
            "hour": 10,
            "recently_added_days": 7,
            "recently_added_limit": 20,
            "include_stats": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "user",
            "smtp_pass": "original-secret",
            "smtp_tls": True,
            "from_addr": "from@example.com",
            "to_addrs": "to@example.com",
        })

        await save_newsletter_config(db, {
            "enabled": True,
            "schedule": "daily",
            "day_of_week": 0,
            "hour": 8,
            "recently_added_days": 3,
            "recently_added_limit": 10,
            "include_stats": False,
            "smtp_host": "mail.example.com",
            "smtp_port": 465,
            "smtp_user": "user",
            "smtp_pass": "***",
            "smtp_tls": False,
            "from_addr": "from@example.com",
            "to_addrs": "to@example.com",
        })

        config = await get_newsletter_config(db)
        from empulse.crypto import decrypt_secret

        # Stored encrypted at rest (I-1) — decrypt to compare the real value.
        assert config["smtp_pass"] != "original-secret"
        assert decrypt_secret(config["smtp_pass"]) == "original-secret"
        assert config["schedule"] == "daily"

    @pytest.mark.asyncio
    async def test_build_newsletter_html(self, db):
        from empulse.newsletter import build_newsletter_html
        config = {"recently_added_days": 7, "recently_added_limit": 10, "include_stats": 1}
        html = await build_newsletter_html(db, config)
        assert "Empulse Newsletter" in html
        assert "Watch Statistics" in html

    @pytest.mark.asyncio
    async def test_build_newsletter_html_recently_added_layout(self, db):
        from empulse.newsletter import build_newsletter_html

        class FakeEmbyClient:
            async def get_recently_added(self, limit=10):
                return [
                    {
                        "Id": "movie-1",
                        "Name": "Arco",
                        "Type": "Movie",
                        "ProductionYear": 2025,
                        "RunTimeTicks": 88 * 600_000_000,
                        "Genres": ["Animation", "Science Fiction"],
                        "CommunityRating": 9.2,
                        "Taglines": ["What if rainbows were people from the future traveling in time?"],
                        "Overview": "Als der Junge Arco aus einer fernen Zukunft zufaellig in die Welt der Iris stuerzt.",
                        "DateCreated": "2026-03-08T12:00:00.0000000Z",
                    },
                    {
                        "Id": "episode-1",
                        "SeriesId": "series-1",
                        "SeriesName": "Dark Winds - Der Wind des Boesen",
                        "Name": "Folge #4.3",
                        "Type": "Episode",
                        "ProductionYear": 2022,
                        "RunTimeTicks": 49 * 600_000_000,
                        "Genres": ["Krimi", "Drama"],
                        "CommunityRating": 8.0,
                        "Overview": "Eine neue Spur fuehrt tiefer in den Fall.",
                        "ParentIndexNumber": 4,
                        "IndexNumber": 3,
                        "DateCreated": "2026-03-08T11:00:00.0000000Z",
                    },
                    {
                        "Id": "episode-2",
                        "SeriesId": "series-1",
                        "SeriesName": "Dark Winds - Der Wind des Boesen",
                        "Name": "Folge #4.2",
                        "Type": "Episode",
                        "ProductionYear": 2022,
                        "RunTimeTicks": 49 * 600_000_000,
                        "Genres": ["Krimi", "Drama"],
                        "CommunityRating": 8.0,
                        "Overview": "Die Ermittlungen gehen weiter.",
                        "ParentIndexNumber": 4,
                        "IndexNumber": 2,
                        "DateCreated": "2026-03-07T11:00:00.0000000Z",
                    },
                ]

            async def get_image_data_url(self, item_id, image_type="Primary", max_width=300):
                return "data:image/jpeg;base64,ZmFrZQ=="

        html = await build_newsletter_html(
            db,
            {"recently_added_days": 7, "recently_added_limit": 10, "include_stats": 0},
            FakeEmbyClient(),
        )

        assert "Recently Added Movies" in html
        assert "1 movie" in html
        assert "Arco" in html
        assert "Animation" in html
        assert "Science Fiction" in html
        assert "Recently Added TV Shows" in html
        assert "1 show / 2 episodes" in html
        assert "Dark Winds - Der Wind des Boesen" in html
        assert "2 episodes" in html
        assert "Season 4 &middot; Episodes 02-03" in html
        assert "data:image/jpeg;base64,ZmFrZQ==" in html
