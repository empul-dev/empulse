import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import websockets

from empulse.config import settings

logger = logging.getLogger("empulse.emby_ws")

# Events that indicate playback state changes
PLAYBACK_EVENTS = {
    "PlaybackStart",
    "PlaybackStopped",
    "PlaybackProgress",
    "SessionEnded",
    "Play",
    "Playstate",
}

# Item types worth notifying on when added to the library (drops Season/folder/BoxSet noise)
NEW_MEDIA_TYPES = {"Movie", "Episode", "Series", "Audio", "MusicAlbum"}


def _parse_emby_date(value: str | None) -> datetime | None:
    """Parse an Emby ISO timestamp (e.g. '2026-08-08T12:00:00.0000000Z') to aware UTC."""
    if not value:
        return None
    s = value.strip().replace("Z", "+00:00")
    # Emby emits 7-digit fractional seconds; fromisoformat only accepts 3 or 6.
    m = re.match(r"(.*\.\d{6})\d*(.*)", s)
    if m:
        s = m.group(1) + m.group(2)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _item_to_data(item: dict) -> dict:
    """Map an Emby item to the notification data shape playback events use."""
    return {
        "item_id": item.get("Id"),
        "item_name": item.get("Name", "Unknown"),
        "item_type": item.get("Type"),
        "series_name": item.get("SeriesName"),
        "series_id": item.get("SeriesId"),
        "year": item.get("ProductionYear"),
    }


def _select_new_items(
    items: list[dict], now: datetime, max_age_minutes: int, cap: int
) -> list[dict]:
    """Filter fetched items to genuinely-new, notifiable ones; aggregate if over cap.

    Returns a list of notification data dicts. Rescans/metadata-refreshes keep
    their old DateCreated and are dropped by the freshness guard. A bulk import
    over `cap` items collapses to a single aggregated notification.
    """
    fresh = []
    for it in items:
        if it.get("Type") not in NEW_MEDIA_TYPES:
            continue
        created = _parse_emby_date(it.get("DateCreated"))
        if created is None:
            continue
        if (now - created).total_seconds() > max_age_minutes * 60:
            continue
        fresh.append(it)

    if not fresh:
        return []
    if len(fresh) > cap:
        return [{"item_name": f"{len(fresh)} new items added", "item_type": "Batch"}]
    return [_item_to_data(it) for it in fresh]


class EmbyWebSocket:
    def __init__(self, poller, emby_client=None, notification_engine=None):
        self.poller = poller
        self.emby_client = emby_client
        self.notification_engine = notification_engine
        base = settings.emby_url.rstrip("/")
        ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
        self.ws_url = f"{ws_base}/embywebsocket"
        self._ws_params = {"api_key": settings.emby_api_key}
        self._pending_added: set[str] = set()
        self._seen_ids: set[str] = set()
        self._debounce_task: asyncio.Task | None = None

    async def run(self):
        """Connect to Emby WebSocket with auto-reconnect."""
        while True:
            try:
                await self._connect()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Emby WS connection error, reconnecting in 5s")
                await asyncio.sleep(5)

    async def _connect(self):
        # Pass API key via header instead of URL params to avoid proxy log exposure
        extra_headers = {"X-Emby-Token": settings.emby_api_key}
        async with websockets.connect(
            self.ws_url, additional_headers=extra_headers
        ) as ws:
            logger.info("Connected to Emby WebSocket")
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("MessageType", "")
                    if msg_type in PLAYBACK_EVENTS:
                        logger.debug(f"Emby WS event: {msg_type}")
                        await self.poller.trigger_poll()
                    elif msg_type == "LibraryChanged":
                        self._on_library_changed(msg.get("Data") or {})
                except json.JSONDecodeError:
                    pass

    def _on_library_changed(self, data: dict):
        if not (self.emby_client and self.notification_engine):
            return
        added = [i for i in (data.get("ItemsAdded") or []) if i]
        if not added:
            return
        self._pending_added.update(added)
        if self._debounce_task is None or self._debounce_task.done():
            self._debounce_task = asyncio.create_task(self._process_new_media())

    async def _process_new_media(self):
        """Debounce, fetch metadata, filter, and emit new_media notifications."""
        await asyncio.sleep(settings.new_media_debounce_seconds)
        ids = self._pending_added - self._seen_ids
        self._pending_added = set()
        if not ids:
            return
        # Mark all attempted up front so a scan re-firing the same IDs can't loop.
        self._seen_ids.update(ids)

        items = []
        for item_id in ids:
            try:
                item = await self.emby_client.get_item(item_id)
            except Exception:
                logger.debug(f"new_media: failed to fetch item {item_id}")
                continue
            if item:
                items.append(item)

        events = _select_new_items(
            items,
            datetime.now(timezone.utc),
            settings.new_media_max_age_minutes,
            settings.new_media_batch_cap,
        )
        if events and events[0].get("item_type") == "Batch":
            logger.info(f"new_media: {events[0]['item_name']} (aggregated)")
        for event_data in events:
            await self.notification_engine.emit("new_media", event_data)
