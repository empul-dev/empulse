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
