import json
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from empulse.app import create_app
from empulse.db import history as history_db


@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked DB."""
    with patch("empulse.app.init_db", new_callable=AsyncMock), \
         patch("empulse.app.settings") as mock_settings:
        mock_settings.emby_api_key = ""  # Disable polling
        mock_settings.emby_url = "http://localhost:8096"
        mock_settings.poll_interval = 10
        mock_settings.db_path = ":memory:"
        mock_settings.auth_password = ""
        mock_settings.secret_key = ""

        app = create_app()

        # We need to mock get_db for route handlers
        import aiosqlite
        from empulse.database import SCHEMA

        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await db.commit()

        with patch("empulse.web.router.get_db", return_value=db), \
             patch("empulse.web.api.get_db", return_value=db), \
             patch("empulse.database.get_db", return_value=db):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                ac._test_db = db  # expose for seeding data
                yield ac

        await db.close()


class TestPageRoutes:
    @pytest.mark.asyncio
    async def test_dashboard(self, client):
        r = await client.get("/")
        assert r.status_code == 200
        assert "Dashboard" in r.text
        assert "Empulse" in r.text

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
    async def test_user_detail_page(self, client):
        from empulse.db import users as users_db
        db = client._test_db
        await users_db.upsert_user(db, {
            "emby_user_id": "u1", "username": "Alice",
            "is_admin": 0, "thumb_url": None, "last_seen": None,
        })
        await history_db.insert_history(db, {
            "session_key": "ud1", "user_id": "u1", "user_name": "Alice",
            "item_id": "m1", "item_name": "Test Movie", "item_type": "Movie",
            "started_at": "2024-01-15T20:00:00", "stopped_at": "2024-01-15T22:00:00",
            "duration_seconds": 7200,
        })
        r = await client.get("/users/u1")
        assert r.status_code == 200
        assert "Alice" in r.text
        assert "Plays" in r.text

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
        assert "Nothing is currently being played" in r.text

    @pytest.mark.asyncio
    async def test_stats_cards(self, client):
        r = await client.get("/api/stats-cards")
        assert r.status_code == 200
        assert "Most Watched Movies" in r.text

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
    async def test_history_table_with_records(self, client):
        """History table renders rows with expand chevrons."""
        db = client._test_db
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "m1",
            "item_name": "Test Movie",
            "item_type": "Movie",
            "year": 2024,
            "client": "Emby Web",
            "device_name": "Chrome",
            "play_method": "DirectPlay",
            "started_at": "2024-01-15T20:00:00",
            "stopped_at": "2024-01-15T22:00:00",
            "duration_seconds": 7200,
            "percent_complete": 95.0,
            "watched": 1,
        })
        r = await client.get("/api/history-table")
        assert r.status_code == 200
        assert "expand-chevron" in r.text
        assert "detail-row" in r.text
        assert "Test Movie" in r.text
        assert "Alice" in r.text
        assert "toggleDetail" in r.text

    @pytest.mark.asyncio
    async def test_history_detail_not_found(self, client):
        """History detail returns error for missing record."""
        r = await client.get("/api/history-detail/99999")
        assert r.status_code == 200
        assert "not found" in r.text.lower()

    @pytest.mark.asyncio
    async def test_history_detail_basic(self, client):
        """History detail renders basic info for record without stream_info."""
        db = client._test_db
        await history_db.insert_history(db, {
            "session_key": "s2",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "m2",
            "item_name": "Another Movie",
            "item_type": "Movie",
            "year": 2023,
            "client": "Emby Web",
            "device_name": "Firefox",
            "play_method": "DirectPlay",
            "video_decision": "Direct Play",
            "audio_decision": "Direct Play",
            "started_at": "2024-01-16T20:00:00",
            "stopped_at": "2024-01-16T22:00:00",
            "duration_seconds": 7200,
        })
        # Get the inserted record's id
        cursor = await db.execute("SELECT id FROM history WHERE item_name = 'Another Movie'")
        row = await cursor.fetchone()
        r = await client.get(f"/api/history-detail/{row[0]}")
        assert r.status_code == 200
        assert "Another Movie" in r.text
        assert "Alice" in r.text
        assert "Firefox" in r.text
        assert "detail-inner" in r.text

    @pytest.mark.asyncio
    async def test_history_detail_with_stream_info(self, client):
        """History detail renders full stream info from JSON."""
        db = client._test_db
        stream_info = json.dumps({
            "video": {"codec": "HEVC", "width": 1920, "height": 1080, "bitrate": 5000000},
            "audio": {"codec": "AAC", "channels": 6, "language": "english"},
            "media": {"container": "MKV", "bitrate": 5500000, "resolution": "1080p"},
            "transcode": {"video_codec": "H264", "width": 1280, "height": 720},
        })
        await history_db.insert_history(db, {
            "session_key": "s3",
            "user_id": "u2",
            "user_name": "Bob",
            "item_id": "m3",
            "item_name": "Streamed Movie",
            "item_type": "Movie",
            "client": "Infuse",
            "device_name": "Apple TV",
            "play_method": "Transcode",
            "video_decision": "Transcode",
            "audio_decision": "Direct Play",
            "stream_info": stream_info,
            "started_at": "2024-01-17T19:00:00",
            "stopped_at": "2024-01-17T21:00:00",
            "duration_seconds": 7200,
        })
        cursor = await db.execute("SELECT id FROM history WHERE item_name = 'Streamed Movie'")
        row = await cursor.fetchone()
        r = await client.get(f"/api/history-detail/{row[0]}")
        assert r.status_code == 200
        assert "HEVC" in r.text
        assert "H264" in r.text
        assert "AAC" in r.text
        assert "Transcode" in r.text
        assert "Bob" in r.text
        assert "Apple TV" in r.text

    @pytest.mark.asyncio
    async def test_chart_daily_plays_empty(self, client):
        r = await client.get("/api/charts/daily-plays?days=7")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 7
        assert all(d["plays"] == 0 for d in data)

    @pytest.mark.asyncio
    async def test_chart_daily_plays_with_data(self, client):
        from datetime import date
        db = client._test_db
        today = date.today().isoformat()
        await history_db.insert_history(db, {
            "session_key": "chart1", "user_id": "u1", "item_type": "Movie",
            "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
            "duration_seconds": 7200,
        })
        r = await client.get("/api/charts/daily-plays?days=7")
        assert r.status_code == 200
        data = r.json()
        plays = [d["plays"] for d in data]
        assert 1 in plays

    @pytest.mark.asyncio
    async def test_chart_plays_by_type(self, client):
        r = await client.get("/api/charts/plays-by-type?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_plays_by_platform(self, client):
        r = await client.get("/api/charts/plays-by-platform?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_user_daily_plays(self, client):
        r = await client.get("/api/charts/user/u1/daily-plays?days=7")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_user_by_type(self, client):
        r = await client.get("/api/charts/user/u1/by-type?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_library_daily_plays(self, client):
        r = await client.get("/api/charts/library/Movie/daily-plays?days=7")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_library_detail_route(self, client):
        r = await client.get("/libraries/Movie")
        assert r.status_code == 200
        assert "Movies" in r.text

    @pytest.mark.asyncio
    async def test_static_css(self, client):
        r = await client.get("/static/css/style.css")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_static_js(self, client):
        r = await client.get("/static/js/app.js")
        assert r.status_code == 200
        assert "WebSocket" in r.text
