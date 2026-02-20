import json
import logging
import time
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger("empulse.notifications")

EVENT_TYPES = [
    "playback_start",
    "playback_stop",
    "playback_pause",
    "playback_resume",
    "watched",
    "transcode",
]

CACHE_TTL = 60  # seconds


class NotificationEngine:
    def __init__(self, db_factory):
        self.get_db = db_factory
        self._channels_cache: list[dict] = []
        self._cache_time: float = 0

    async def _load_channels(self) -> list[dict]:
        now = time.monotonic()
        if self._channels_cache and (now - self._cache_time) < CACHE_TTL:
            return self._channels_cache

        db = self.get_db()
        cursor = await db.execute(
            "SELECT * FROM notification_channels WHERE enabled = 1"
        )
        rows = await cursor.fetchall()
        self._channels_cache = [dict(r) for r in rows]
        self._cache_time = now
        return self._channels_cache

    def invalidate_cache(self):
        self._cache_time = 0

    async def emit(self, event_type: str, data: dict):
        if event_type not in EVENT_TYPES:
            return

        channels = await self._load_channels()
        for ch in channels:
            try:
                triggers = json.loads(ch.get("triggers", "[]"))
            except (json.JSONDecodeError, TypeError):
                triggers = []

            if event_type not in triggers:
                continue

            if not self._check_conditions(ch, data):
                continue

            await self._dispatch(ch, event_type, data)

    def _check_conditions(self, channel: dict, data: dict) -> bool:
        try:
            conditions = json.loads(channel.get("conditions", "{}"))
        except (json.JSONDecodeError, TypeError):
            return True

        if not conditions:
            return True

        users = conditions.get("users", [])
        if users and data.get("user_id") not in users:
            return False

        types = conditions.get("types", [])
        if types and data.get("item_type") not in types:
            return False

        min_duration = conditions.get("min_duration", 0)
        if min_duration and data.get("duration_seconds", 0) < min_duration:
            return False

        return True

    async def _dispatch(self, channel: dict, event_type: str, data: dict):
        channel_type = channel.get("channel_type", "")
        try:
            config = json.loads(channel.get("config", "{}"))
        except (json.JSONDecodeError, TypeError):
            config = {}

        summary = self._build_summary(event_type, data)
        error = None
        status = "sent"

        try:
            if channel_type == "discord":
                from empulse.notifications.channels.discord import send_discord
                await send_discord(config, event_type, data)
            elif channel_type == "webhook":
                from empulse.notifications.channels.webhook import send_webhook
                await send_webhook(config, event_type, data)
            else:
                logger.warning(f"Unknown channel type: {channel_type}")
                return
        except Exception as e:
            logger.error(f"Notification failed for channel {channel.get('name')}: {e}")
            error = str(e)[:500]
            status = "failed"

        await self._log(channel["id"], event_type, summary, status, error)

    def _build_summary(self, event_type: str, data: dict) -> str:
        user = data.get("user_name", "Unknown")
        title = data.get("item_name", "Unknown")
        series = data.get("series_name")
        if series:
            title = f"{series} - {title}"
        labels = {
            "playback_start": "started",
            "playback_stop": "stopped",
            "playback_pause": "paused",
            "playback_resume": "resumed",
            "watched": "watched",
            "transcode": "is transcoding",
        }
        verb = labels.get(event_type, event_type)
        return f"{user} {verb} {title}"

    async def _log(self, channel_id: int, event_type: str, summary: str, status: str, error: str | None):
        db = self.get_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO notification_log (channel_id, event_type, event_summary, status, error, sent_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [channel_id, event_type, summary, status, error, now],
        )
        await db.commit()

    async def send_test(self, channel: dict) -> tuple[bool, str]:
        """Send a test notification to a channel. Returns (success, message)."""
        channel_type = channel.get("channel_type", "")
        try:
            config = json.loads(channel.get("config", "{}"))
        except (json.JSONDecodeError, TypeError):
            return False, "Invalid channel config"

        test_data = {
            "user_name": "Test User",
            "item_name": "Test Movie",
            "item_type": "Movie",
            "play_method": "DirectPlay",
            "client": "Empulse",
            "device_name": "Test Device",
            "duration_seconds": 7200,
            "percent_complete": 50.0,
        }

        try:
            if channel_type == "discord":
                from empulse.notifications.channels.discord import send_discord
                await send_discord(config, "playback_start", test_data)
            elif channel_type == "webhook":
                from empulse.notifications.channels.webhook import send_webhook
                await send_webhook(config, "playback_start", test_data)
            else:
                return False, f"Unknown channel type: {channel_type}"
            return True, "Test notification sent"
        except Exception as e:
            return False, str(e)
