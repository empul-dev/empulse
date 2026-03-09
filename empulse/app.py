import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from importlib.metadata import version as pkg_version, PackageNotFoundError

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.requests import Request
from starlette.responses import Response

from empulse.config import settings
from empulse.database import init_db, get_db
from empulse.formatting import (
    format_date,
    format_time,
    format_datetime,
    format_date_short,
    format_last_seen,
)

logger = logging.getLogger("empulse")

BASE_DIR = Path(__file__).parent


def get_version() -> str:
    try:
        return pkg_version("empulse")
    except PackageNotFoundError:
        return "dev"


class EmpulseTemplates(Jinja2Templates):
    """Auto-inject current_user, CSP nonce, and display settings into all template contexts."""

    def TemplateResponse(self, request: Request, name: str, context: dict | None = None, **kwargs):
        context = dict(context or {})
        context.setdefault("request", request)
        if request:
            if not context.get("current_user"):
                context["current_user"] = getattr(request.state, "user", None)
            if not context.get("csp_nonce"):
                context["csp_nonce"] = getattr(request.state, "csp_nonce", "")
            if "update_available" not in context:
                checker = getattr(request.app.state, "update_checker", None)
                context["update_available"] = bool(
                    checker and checker.info.update_available
                )
            if "display" not in context:
                from empulse.formatting import DEFAULT_DISPLAY

                context["display"] = getattr(
                    request.app.state, "display_settings", DEFAULT_DISPLAY
                )
        return super().TemplateResponse(request, name, context, **kwargs)


templates = EmpulseTemplates(directory=str(BASE_DIR / "templates"))
templates.env.globals["cache_v"] = str(int(time.time()))
templates.env.globals["version"] = get_version()

templates.env.filters["fmt_date"] = format_date
templates.env.filters["fmt_time"] = format_time
templates.env.filters["fmt_datetime"] = format_datetime
templates.env.filters["fmt_date_short"] = format_date_short
templates.env.filters["fmt_last_seen"] = format_last_seen


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")

    db = get_db()

    # Load display settings into app state
    from empulse.db.display import get_display_settings

    app.state.display_settings = await get_display_settings(db)
    logger.info(f"Display settings: tz={app.state.display_settings['timezone']}")

    # Invalidate all login sessions on startup so restarts force re-login
    await db.execute("DELETE FROM login_sessions")
    await db.commit()
    logger.info("All login sessions cleared on startup")

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
    poster_cache_task = None
    update_checker_task = None

    from empulse.notifications.engine import NotificationEngine

    notification_engine = NotificationEngine(get_db)
    app.state.notification_engine = notification_engine

    if not settings.disable_update_check:
        from empulse.update_checker import UpdateChecker

        update_checker = UpdateChecker(get_version(), settings.update_check_interval)
        app.state.update_checker = update_checker
        update_checker_task = asyncio.create_task(update_checker.run())
        logger.info("Update checker started")

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

        from empulse.web.poster_cache import PosterWallCache

        poster_cache = PosterWallCache(emby_client)
        poster_cache_task = asyncio.create_task(poster_cache.run())
        app.state.poster_cache = poster_cache
        logger.info("Poster wall cache started")
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
    if poster_cache_task:
        poster_cache_task.cancel()
        try:
            await poster_cache_task
        except asyncio.CancelledError:
            pass
    if update_checker_task:
        update_checker_task.cancel()
        try:
            await update_checker_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app = FastAPI(title="Empulse", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    from empulse.web.router import router as web_router
    from empulse.web.api import router as api_router
    from empulse.web.websocket import router as ws_router

    app.include_router(web_router)
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        if request.headers.get("hx-request"):
            return Response(status_code=404)
        return templates.TemplateResponse(request, "404.html", status_code=404)

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc):
        if request.headers.get("hx-request"):
            return Response(status_code=500)
        return templates.TemplateResponse(request, "500.html", status_code=500)

    # Auth middleware is always active — authentication is mandatory.
    # If no AUTH_PASSWORD or EMBY_API_KEY is configured, the login page
    # will show a setup message prompting the admin to configure auth.
    from empulse.web.auth import AuthMiddleware

    app.add_middleware(
        AuthMiddleware,
        secret=settings.secret_key,
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        # Generate per-request nonce for CSP script-src
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss: https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    return app
