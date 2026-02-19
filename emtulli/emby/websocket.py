import asyncio
import json
import logging

import websockets

from emtulli.config import settings

logger = logging.getLogger("emtulli.emby_ws")

# Events that indicate playback state changes
PLAYBACK_EVENTS = {
    "PlaybackStart",
    "PlaybackStopped",
    "PlaybackProgress",
    "SessionEnded",
    "Play",
    "Playstate",
}


class EmbyWebSocket:
    def __init__(self, poller):
        self.poller = poller
        base = settings.emby_url.rstrip("/")
        self.ws_url = base.replace("http://", "ws://").replace("https://", "wss://")
        self.ws_url += f"/embywebsocket?api_key={settings.emby_api_key}"

    async def run(self):
        """Connect to Emby WebSocket with auto-reconnect."""
        while True:
            try:
                await self._connect()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Emby WS error: {e}, reconnecting in 5s")
                await asyncio.sleep(5)

    async def _connect(self):
        async with websockets.connect(self.ws_url) as ws:
            logger.info("Connected to Emby WebSocket")
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("MessageType", "")
                    if msg_type in PLAYBACK_EVENTS:
                        logger.debug(f"Emby WS event: {msg_type}")
                        await self.poller.trigger_poll()
                except json.JSONDecodeError:
                    pass
