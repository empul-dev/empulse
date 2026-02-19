import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from emtulli.app import create_app


@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked DB."""
    with patch("emtulli.app.init_db", new_callable=AsyncMock), \
         patch("emtulli.app.settings") as mock_settings:
        mock_settings.emby_api_key = ""  # Disable polling
        mock_settings.emby_url = "http://localhost:8096"
        mock_settings.poll_interval = 10
        mock_settings.db_path = ":memory:"

        app = create_app()

        # We need to mock get_db for route handlers
        import aiosqlite
        from emtulli.database import SCHEMA

        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await db.commit()

        with patch("emtulli.web.router.get_db", return_value=db), \
             patch("emtulli.web.api.get_db", return_value=db), \
             patch("emtulli.database.get_db", return_value=db):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

        await db.close()


class TestPageRoutes:
    @pytest.mark.asyncio
    async def test_dashboard(self, client):
        r = await client.get("/")
        assert r.status_code == 200
        assert "Dashboard" in r.text
        assert "Emtulli" in r.text

    @pytest.mark.asyncio
    async def test_history_page(self, client):
        r = await client.get("/history")
        assert r.status_code == 200
        assert "History" in r.text

    @pytest.mark.asyncio
    async def test_users_page(self, client):
        r = await client.get("/users")
        assert r.status_code == 200
        assert "Users" in r.text

    @pytest.mark.asyncio
    async def test_libraries_page(self, client):
        r = await client.get("/libraries")
        assert r.status_code == 200
        assert "Libraries" in r.text

    @pytest.mark.asyncio
    async def test_settings_page(self, client):
        r = await client.get("/settings")
        assert r.status_code == 200
        assert "Settings" in r.text


class TestAPIRoutes:
    @pytest.mark.asyncio
    async def test_now_playing_empty(self, client):
        r = await client.get("/api/now-playing")
        assert r.status_code == 200
        assert "No active streams" in r.text

    @pytest.mark.asyncio
    async def test_stats_cards(self, client):
        r = await client.get("/api/stats-cards")
        assert r.status_code == 200
        assert "Total Plays" in r.text
        assert "0" in r.text

    @pytest.mark.asyncio
    async def test_recent_history_empty(self, client):
        r = await client.get("/api/recent-history")
        assert r.status_code == 200
        assert "No history records" in r.text

    @pytest.mark.asyncio
    async def test_history_table_empty(self, client):
        r = await client.get("/api/history-table")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_static_css(self, client):
        r = await client.get("/static/css/style.css")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_static_js(self, client):
        r = await client.get("/static/js/app.js")
        assert r.status_code == 200
        assert "WebSocket" in r.text
