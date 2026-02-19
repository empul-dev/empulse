import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from emtulli.config import settings
from emtulli.database import init_db, get_db

logger = logging.getLogger("emtulli")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")

    poller_task = None
    ws_task = None

    if settings.emby_api_key:
        from emtulli.activity.poller import SessionPoller
        from emtulli.emby.client import EmbyClient
        from emtulli.activity.processor import ActivityProcessor
        from emtulli.activity.session_state import SessionStateTracker
        from emtulli.web.websocket import manager as ws_manager

        emby_client = EmbyClient()
        state_tracker = SessionStateTracker()
        processor = ActivityProcessor(state_tracker, get_db)
        poller = SessionPoller(emby_client, processor, ws_manager)

        app.state.emby_client = emby_client
        app.state.poller = poller
        app.state.ws_manager = ws_manager
        app.state.state_tracker = state_tracker

        poller_task = asyncio.create_task(poller.run())
        logger.info("Session poller started")

        from emtulli.emby.websocket import EmbyWebSocket
        emby_ws = EmbyWebSocket(poller)
        ws_task = asyncio.create_task(emby_ws.run())
        app.state.emby_ws = emby_ws
        logger.info("Emby WebSocket listener started")
    else:
        logger.warning("No EMBY_API_KEY configured - polling disabled")

    yield

    if poller_task:
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass
    if ws_task:
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = FastAPI(title="Emtulli", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    from emtulli.web.router import router as web_router
    from emtulli.web.api import router as api_router
    from emtulli.web.websocket import router as ws_router

    app.include_router(web_router)
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    if settings.auth_password:
        from emtulli.web.auth import AuthMiddleware
        app.add_middleware(
            AuthMiddleware,
            password=settings.auth_password,
            secret=settings.secret_key or settings.auth_password,
        )

    return app
