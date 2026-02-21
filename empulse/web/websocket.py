import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("empulse.ws")
router = APIRouter()


class BrowserWSManager:
    MAX_CONNECTIONS = 100

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        if len(self.connections) >= self.MAX_CONNECTIONS:
            await ws.close(code=1013)  # Try Again Later
            return
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
    from empulse.config import settings
    if settings.auth_password or settings.emby_api_key:
        from empulse.web.auth import verify_session_token, hash_token, COOKIE_NAME
        from empulse.database import get_db

        token = ws.cookies.get(COOKIE_NAME)
        if not token or verify_session_token(token, settings.secret_key) is None:
            await ws.close(code=1008)
            return

        # Check DB for revoked session (same check as AuthMiddleware)
        db = get_db()
        token_h = hash_token(token)
        cursor = await db.execute(
            "SELECT revoked FROM login_sessions WHERE token_hash = ?",
            [token_h],
        )
        row = await cursor.fetchone()
        if not row or row["revoked"]:
            await ws.close(code=1008)
            return

    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
