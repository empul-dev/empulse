import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("emtulli.ws")
router = APIRouter()


class BrowserWSManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        logger.debug(f"Browser WS connected ({len(self.connections)} total)")

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)
        logger.debug(f"Browser WS disconnected ({len(self.connections)} total)")

    async def broadcast(self, target: str):
        msg = json.dumps({"type": "refresh", "target": target})
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)


manager = BrowserWSManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Authenticate WebSocket connections when auth is enabled
    from emtulli.config import settings
    if settings.auth_password:
        from emtulli.web.auth import verify_session_token, COOKIE_NAME
        token = ws.cookies.get(COOKIE_NAME)
        if not token or not verify_session_token(token, settings.secret_key):
            await ws.close(code=1008)
            return

    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
