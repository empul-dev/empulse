import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.requests import Request
from starlette.templating import _TemplateResponse

from empulse.config import settings
from empulse.database import init_db, get_db

logger = logging.getLogger("empulse")

BASE_DIR = Path(__file__).parent


class EmpulseTemplates(Jinja2Templates):
    """Auto-inject current_user into all template contexts."""

    def TemplateResponse(self, name, context, **kwargs):
        request: Request | None = context.get("request")
        if request and not context.get("current_user"):
            context["current_user"] = getattr(request.state, "user", None)
        return super().TemplateResponse(name, context, **kwargs)


templates = EmpulseTemplates(directory=str(BASE_DIR / "templates"))
templates.env.globals["cache_v"] = str(int(time.time()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")

    # Create EmbyClient for auth even without api_key (needs emby_url)
    from empulse.emby.client import EmbyClient
    auth_emby_client = EmbyClient()
    app.state.emby_client = auth_emby_client

    if not settings.auth_password and not settings.emby_api_key:
        logger.warning(
            "No AUTH_PASSWORD or EMBY_API_KEY set — the application is accessible without authentication! "
            "Set AUTH_PASSWORD in your .env file or configure EMBY_API_KEY to enable authentication."
        )

    poller_task = None
    ws_task = None
    newsletter_task = None

    from empulse.notifications.engine import NotificationEngine
    notification_engine = NotificationEngine(get_db)
    app.state.notification_engine = notification_engine

    if settings.emby_api_key:
        from empulse.activity.poller import SessionPoller
        from empulse.activity.processor import ActivityProcessor
        from empulse.activity.session_state import SessionStateTracker
        from empulse.web.websocket import manager as ws_manager

        emby_client = auth_emby_client  # Reuse the already-created client
        state_tracker = SessionStateTracker()
        processor = ActivityProcessor(state_tracker, get_db)
        processor.notification_engine = notification_engine
        poller = SessionPoller(emby_client, processor, ws_manager)

        app.state.emby_client = emby_client
        app.state.poller = poller
        app.state.ws_manager = ws_manager
        app.state.state_tracker = state_tracker

        poller_task = asyncio.create_task(poller.run())
        logger.info("Session poller started")

        from empulse.newsletter import NewsletterScheduler
        newsletter_scheduler = NewsletterScheduler(get_db, emby_client)
        newsletter_task = asyncio.create_task(newsletter_scheduler.run())
        logger.info("Newsletter scheduler started")

        from empulse.emby.websocket import EmbyWebSocket
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
    if newsletter_task:
        newsletter_task.cancel()
        try:
            await newsletter_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = FastAPI(title="Empulse", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    from empulse.web.router import router as web_router
    from empulse.web.api import router as api_router
    from empulse.web.websocket import router as ws_router

    app.include_router(web_router)
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    if settings.auth_password or settings.emby_api_key:
        from empulse.web.auth import AuthMiddleware
        app.add_middleware(
            AuthMiddleware,
            secret=settings.secret_key,
        )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'"
        )
        return response

    return app
