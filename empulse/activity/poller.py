import asyncio
import logging

from empulse.config import settings
from empulse.emby.client import EmbyClient
from empulse.activity.processor import ActivityProcessor
from empulse.web.websocket import BrowserWSManager

logger = logging.getLogger("empulse.poller")


class SessionPoller:
    def __init__(self, client: EmbyClient, processor: ActivityProcessor, ws_manager: BrowserWSManager):
        self.client = client
        self.processor = processor
        self.ws_manager = ws_manager
        self._poll_event = asyncio.Event()

    async def trigger_poll(self):
        """Trigger an immediate poll (called from WebSocket listener)."""
        self._poll_event.set()

    async def run(self):
        """Main polling loop."""
        logger.info(f"Poller starting (interval: {settings.poll_interval}s)")
        await self._sync_metadata()

        while True:
            try:
                await self._poll()
                await self.ws_manager.broadcast("now-playing")
            except Exception as e:
                logger.error(f"Poll error: {e}")

            # Wait for either the interval or an immediate trigger
            try:
                await asyncio.wait_for(
                    self._poll_event.wait(),
                    timeout=settings.poll_interval,
                )
                self._poll_event.clear()
            except asyncio.TimeoutError:
                pass

    async def _poll(self):
        sessions = await self.client.get_sessions()
        await self.processor.process_sessions(sessions)

    async def _sync_metadata(self):
        """Sync users and libraries from Emby on startup."""
        try:
            from empulse.database import get_db
            from empulse.db import users as users_db, libraries as libraries_db

            db = get_db()

            # Sync server info
            info = await self.client.get_server_info()
            await libraries_db.upsert_server_info(db, {
                "server_name": info.get("ServerName", ""),
                "version": info.get("Version", ""),
                "local_address": info.get("LocalAddress", ""),
                "wan_address": info.get("WanAddress", ""),
                "os": info.get("OperatingSystem", ""),
            })

            # Sync users
            emby_users = await self.client.get_users()
            for u in emby_users:
                is_admin = u.policy.is_administrator if u.policy else False
                await users_db.upsert_user(db, {
                    "emby_user_id": u.id,
                    "username": u.name,
                    "is_admin": 1 if is_admin else 0,
                    "thumb_url": self.client.get_user_image_url(u.id) if u.primary_image_tag else None,
                    "last_seen": None,
                })

            # Sync libraries
            libs = await self.client.get_libraries()
            for lib in libs:
                count = await self.client.get_library_item_count(lib.id)
                await libraries_db.upsert_library(db, {
                    "emby_library_id": lib.id,
                    "name": lib.name,
                    "library_type": lib.collection_type or "unknown",
                    "item_count": count,
                })

            logger.info(f"Metadata synced: {len(emby_users)} users, {len(libs)} libraries")
        except Exception as e:
            logger.error(f"Metadata sync failed: {e}")
