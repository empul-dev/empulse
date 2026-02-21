import asyncio
import json
import logging

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


class EmbyWebSocket:
    def __init__(self, poller):
        self.poller = poller
        base = settings.emby_url.rstrip("/")
        ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
        self.ws_url = f"{ws_base}/embywebsocket"
        self._ws_params = {"api_key": settings.emby_api_key}

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
                except json.JSONDecodeError:
                    pass
