import json
import pytest
import pytest_asyncio
import aiosqlite

from empulse.database import SCHEMA
from empulse.notifications.engine import NotificationEngine


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
        import time
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


class TestGeoLocation:
    @pytest.mark.asyncio
    async def test_private_ip_returns_none(self, db):
        from empulse.geo import lookup_ip
        result = await lookup_ip(db, "192.168.1.1")
        assert result is None
        result = await lookup_ip(db, "127.0.0.1")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_ip_returns_none(self, db):
        from empulse.geo import lookup_ip
        result = await lookup_ip(db, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_cached_result(self, db):
        from empulse.geo import lookup_ip
        # Insert a cached result
        await db.execute(
            "INSERT INTO ip_locations (ip, city, country, latitude, longitude) VALUES (?, ?, ?, ?, ?)",
            ["8.8.8.8", "Mountain View", "United States", 37.386, -122.084],
        )
        await db.commit()
        result = await lookup_ip(db, "8.8.8.8")
        assert result is not None
        assert result["city"] == "Mountain View"
        assert result["country"] == "United States"

    @pytest.mark.asyncio
    async def test_get_all_locations_empty(self, db):
        from empulse.geo import get_all_locations
        result = await get_all_locations(db)
        assert result == []


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
    async def test_build_newsletter_html(self, db):
        from empulse.newsletter import build_newsletter_html
        config = {"recently_added_days": 7, "recently_added_limit": 10, "include_stats": 1}
        html = await build_newsletter_html(db, config)
        assert "Empulse Newsletter" in html
        assert "Watch Statistics" in html
