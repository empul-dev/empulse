import asyncio
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from empulse import database
from empulse.activity.poller import SessionPoller
from empulse.app import create_app
from empulse.config import settings
from empulse.emby.websocket import EmbyWebSocket
from empulse.newsletter import NewsletterScheduler, get_newsletter_config
from empulse.web.poster_cache import PosterWallCache


async def test_startup_and_shutdown_preserve_background_services(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "empulse.db"))
    monkeypatch.setattr(settings, "emby_api_key", "test-api-key")
    monkeypatch.setattr(settings, "disable_update_check", True)
    monkeypatch.setattr(database, "_db", None)
    monkeypatch.setattr("empulse.emby.client.EmbyClient", AsyncMock)

    services = (SessionPoller, EmbyWebSocket, NewsletterScheduler, PosterWallCache)
    started = {service: asyncio.Event() for service in services}
    stopped = {service: asyncio.Event() for service in services}

    def run_service(service):
        async def run(self):
            started[service].set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped[service].set()

        return run

    for service in services:
        monkeypatch.setattr(service, "run", run_service(service))

    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in started.values())),
                timeout=2,
            )
            assert isinstance(app.state.poller, SessionPoller)
            assert app.state.emby_ws.poller is app.state.poller
            assert await get_newsletter_config(database.get_db()) is None
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/login")
            assert response.status_code == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"

        assert all(event.is_set() for event in stopped.values())
    finally:
        if database._db is not None:
            await database._db.close()
