import json
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from empulse.app import create_app
from empulse.db import history as history_db, libraries as libraries_db
from empulse.update_checker import UpdateInfo
from empulse.web.auth import (
    create_session_token,
    hash_token,
    COOKIE_NAME,
    SESSION_MAX_AGE,
)


@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked DB and an authenticated admin session."""
    with (
        patch("empulse.app.init_db", new_callable=AsyncMock),
        patch("empulse.app.settings") as mock_settings,
    ):
        mock_settings.emby_api_key = ""
        mock_settings.emby_url = "http://localhost:8096"
        mock_settings.poll_interval = 10
        mock_settings.db_path = ":memory:"
        mock_settings.auth_password = "testpass"
        mock_settings.secret_key = "testsecret"
        mock_settings.disable_update_check = True
        mock_settings.update_check_interval = 43200

        app = create_app()

        import aiosqlite
        from empulse.database import SCHEMA

        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await db.commit()

        # Create a valid admin session
        token = create_session_token("testsecret", "__admin__", "admin")
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=SESSION_MAX_AGE)
        await db.execute(
            """INSERT INTO login_sessions
               (token_hash, emby_user_id, username, role, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                hash_token(token),
                None,
                "TestAdmin",
                "admin",
                now.isoformat(),
                expires.isoformat(),
            ],
        )
        await db.commit()

        with (
            patch("empulse.web.router.get_db", return_value=db),
            patch("empulse.web.api.get_db", return_value=db),
            patch("empulse.database.get_db", return_value=db),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                headers={"Origin": "http://test"},
            ) as ac:
                ac.cookies.set(COOKIE_NAME, token)
                ac._test_db = db  # expose for seeding data
                ac._test_app = app
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
    async def test_unwatched_page(self, client):
        db = client._test_db
        await libraries_db.upsert_library(
            db,
            {
                "emby_library_id": "tv-lib-1",
                "name": "TV Shows",
                "library_type": "tvshows",
                "item_count": 50,
            },
        )
        await libraries_db.upsert_library(
            db,
            {
                "emby_library_id": "movie-lib-1",
                "name": "Movies",
                "library_type": "movies",
                "item_count": 80,
            },
        )

        r = await client.get(
            "/unwatched?library_id=tv-lib-1&sort=year_desc&page_size=25"
        )

        assert r.status_code == 200
        assert "Unwatched" in r.text
        assert "/api/unwatched" in r.text
        assert "TV Shows" in r.text
        assert "Movies" in r.text
        assert (
            "/api/unwatched-table?page=1&amp;page_size=25&amp;search=&amp;sort=year_desc&amp;library_id=tv-lib-1"
            in r.text
        )
        assert "All libraries" in r.text

    @pytest.mark.asyncio
    async def test_user_detail_page(self, client):
        from empulse.db import users as users_db

        db = client._test_db
        await users_db.upsert_user(
            db,
            {
                "emby_user_id": "u1",
                "username": "Alice",
                "is_admin": 0,
                "thumb_url": None,
                "last_seen": None,
            },
        )
        await history_db.insert_history(
            db,
            {
                "session_key": "ud1",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "m1",
                "item_name": "Test Movie",
                "item_type": "Movie",
                "started_at": "2024-01-15T20:00:00",
                "stopped_at": "2024-01-15T22:00:00",
                "duration_seconds": 7200,
            },
        )
        r = await client.get("/users/u1")
        assert r.status_code == 200
        assert "Alice" in r.text
        assert "Plays" in r.text

    @pytest.mark.asyncio
    async def test_settings_page(self, client):
        r = await client.get("/settings")
        assert r.status_code == 200
        assert "Settings" in r.text

    @pytest.mark.asyncio
    async def test_settings_page_shows_update_status(self, client):
        class StubChecker:
            def __init__(self):
                self.info = UpdateInfo(
                    update_available=True,
                    latest_version="0.2.3",
                    current_version="0.2.1",
                    release_url="https://github.com/empul-dev/empulse/releases/tag/v0.2.3",
                    last_checked_at="2026-03-10T08:30:00+00:00",
                )

        client._test_app.state.update_checker = StubChecker()

        r = await client.get("/settings")

        assert r.status_code == 200
        assert "Update available: v0.2.3" in r.text
        assert "Current version: v0.2.1" in r.text
        assert "Check for Updates" in r.text


async def _create_viewer_session(db, user_id: str, username: str) -> str:
    """Insert a viewer login session directly (mirrors the admin session set
    up by the `client` fixture) and return the raw token, so tests can send
    it as an override cookie for individual requests."""
    from empulse.db import users as users_db

    await users_db.upsert_user(
        db,
        {
            "emby_user_id": user_id,
            "username": username,
            "is_admin": 0,
            "thumb_url": None,
            "last_seen": None,
        },
    )
    await users_db.set_user_enabled(db, user_id, True)

    token = create_session_token("testsecret", user_id, "viewer")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=SESSION_MAX_AGE)
    await db.execute(
        """INSERT INTO login_sessions
           (token_hash, emby_user_id, username, role, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [hash_token(token), user_id, username, "viewer", now.isoformat(), expires.isoformat()],
    )
    await db.commit()
    return token


class TestUserScopedHistoryAccess:
    """E-1: non-admin viewers can only see their own history/user data."""

    async def _seed_two_users(self, db):
        from empulse.db import users as users_db

        await users_db.upsert_user(
            db,
            {"emby_user_id": "u1", "username": "Alice", "is_admin": 0, "thumb_url": None, "last_seen": None},
        )
        await users_db.upsert_user(
            db,
            {"emby_user_id": "u2", "username": "Bob", "is_admin": 0, "thumb_url": None, "last_seen": None},
        )
        await history_db.insert_history(
            db,
            {
                "session_key": "s-u1", "user_id": "u1", "user_name": "Alice",
                "item_id": "m1", "item_name": "Alice Movie", "item_type": "Movie",
                "started_at": "2024-01-15T20:00:00", "stopped_at": "2024-01-15T22:00:00",
                "duration_seconds": 7200,
            },
        )
        await history_db.insert_history(
            db,
            {
                "session_key": "s-u2", "user_id": "u2", "user_name": "Bob",
                "item_id": "m2", "item_name": "Bob Movie", "item_type": "Movie",
                "started_at": "2024-01-16T20:00:00", "stopped_at": "2024-01-16T22:00:00",
                "duration_seconds": 7200,
            },
        )

    @pytest.mark.asyncio
    async def test_viewer_can_see_own_user_page(self, client):
        db = client._test_db
        await self._seed_two_users(db)
        token = await _create_viewer_session(db, "u1", "Alice")

        client.cookies.set(COOKIE_NAME, token)
        r = await client.get("/users/u1")
        assert r.status_code == 200
        assert "Alice" in r.text

    @pytest.mark.asyncio
    async def test_viewer_gets_403_on_other_users_page(self, client):
        db = client._test_db
        await self._seed_two_users(db)
        token = await _create_viewer_session(db, "u1", "Alice")

        client.cookies.set(COOKIE_NAME, token)
        r = await client.get("/users/u2")
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_unaffected_by_user_scoping(self, client):
        db = client._test_db
        await self._seed_two_users(db)

        r = await client.get("/users/u2")  # default client cookie = admin
        assert r.status_code == 200
        assert "Bob" in r.text

    @pytest.mark.asyncio
    async def test_history_table_scopes_to_self_for_viewer(self, client):
        db = client._test_db
        await self._seed_two_users(db)
        token = await _create_viewer_session(db, "u1", "Alice")

        # Even explicitly requesting another user's data, a viewer only ever
        # sees their own — the filter is silently overridden, not rejected.
        client.cookies.set(COOKIE_NAME, token)
        r = await client.get("/api/history-table?user_id=u2")
        assert r.status_code == 200
        assert "Alice Movie" in r.text
        assert "Bob Movie" not in r.text

    @pytest.mark.asyncio
    async def test_history_table_shows_all_for_admin(self, client):
        db = client._test_db
        await self._seed_two_users(db)

        r = await client.get("/api/history-table")
        assert r.status_code == 200
        assert "Alice Movie" in r.text
        assert "Bob Movie" in r.text

    @pytest.mark.asyncio
    async def test_history_detail_forbidden_for_other_users_record(self, client):
        db = client._test_db
        await self._seed_two_users(db)
        token = await _create_viewer_session(db, "u1", "Alice")

        cursor = await db.execute("SELECT id FROM history WHERE user_id = 'u2'")
        row = await cursor.fetchone()
        history_id = row["id"]

        client.cookies.set(COOKIE_NAME, token)
        r = await client.get(f"/api/history-detail/{history_id}")
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_user_daily_plays_chart_forbidden_for_other_user(self, client):
        db = client._test_db
        await self._seed_two_users(db)
        token = await _create_viewer_session(db, "u1", "Alice")

        client.cookies.set(COOKIE_NAME, token)
        r = await client.get("/api/charts/user/u2/daily-plays")
        assert r.status_code == 403


class TestApiRateLimit:
    """D-1: authenticated /api/* usage is rate limited per user."""

    @pytest.mark.asyncio
    async def test_exceeding_limit_returns_429(self, client):
        from empulse.web.rate_limit import api_limiter

        api_limiter.limit = 3
        try:
            for _ in range(3):
                r = await client.get("/api/now-playing")
                assert r.status_code == 200
            r = await client.get("/api/now-playing")
            assert r.status_code == 429
            assert r.headers.get("retry-after") == "60"
        finally:
            api_limiter.limit = 120

    @pytest.mark.asyncio
    async def test_users_have_independent_buckets(self, client):
        from empulse.db import users as users_db
        from empulse.web.rate_limit import api_limiter

        await users_db.upsert_user(
            client._test_db,
            {"emby_user_id": "u1", "username": "Alice", "is_admin": 0, "thumb_url": None, "last_seen": None},
        )
        await users_db.set_user_enabled(client._test_db, "u1", True)
        viewer_token = await _create_viewer_session(client._test_db, "u1", "Alice")

        api_limiter.limit = 1
        try:
            r = await client.get("/api/now-playing")  # admin's 1 request
            assert r.status_code == 200

            client.cookies.set(COOKIE_NAME, viewer_token)
            r = await client.get("/api/now-playing")  # viewer has their own budget
            assert r.status_code == 200
        finally:
            api_limiter.limit = 120

    @pytest.mark.asyncio
    async def test_non_api_routes_unaffected(self, client):
        from empulse.web.rate_limit import api_limiter

        api_limiter.limit = 1
        try:
            for _ in range(5):
                r = await client.get("/")
                assert r.status_code == 200
        finally:
            api_limiter.limit = 120


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
    async def test_stats_cards_show_links_use_series_id(self, client):
        db = client._test_db
        today = datetime.now(timezone.utc).date().isoformat()
        await history_db.insert_history(
            db,
            {
                "session_key": "show-old",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "25450",
                "item_name": "Pilot",
                "item_type": "Episode",
                "series_name": "The Pitt",
                "series_id": "",
                "started_at": f"{today}T20:00:00",
                "stopped_at": f"{today}T20:30:00",
                "duration_seconds": 1800,
            },
        )
        await history_db.insert_history(
            db,
            {
                "session_key": "show-new",
                "user_id": "u2",
                "user_name": "Bob",
                "item_id": "25451",
                "item_name": "Episode 2",
                "item_type": "Episode",
                "series_name": "The Pitt",
                "series_id": "35974",
                "started_at": f"{today}T21:00:00",
                "stopped_at": f"{today}T21:30:00",
                "duration_seconds": 1800,
            },
        )

        r = await client.get("/api/stats-cards?days=365")

        assert r.status_code == 200
        assert "/item/35974?type=series&name=The%20Pitt" in r.text
        assert "/item/25450?type=series&name=The%20Pitt" not in r.text

    @pytest.mark.asyncio
    async def test_stats_cards_include_hover_metadata_for_users_libraries_platforms(
        self, client
    ):
        db = client._test_db
        today = datetime.now(timezone.utc).date().isoformat()
        await history_db.insert_history(
            db,
            {
                "session_key": "hover-users",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "m1",
                "item_name": "Movie One",
                "item_type": "Movie",
                "client": "Emby Web",
                "started_at": f"{today}T20:00:00",
                "stopped_at": f"{today}T21:00:00",
                "duration_seconds": 3600,
            },
        )
        await history_db.insert_history(
            db,
            {
                "session_key": "hover-tv",
                "user_id": "u2",
                "user_name": "Bob",
                "item_id": "e1",
                "item_name": "Episode One",
                "item_type": "Episode",
                "series_name": "Show",
                "series_id": "s1",
                "client": "Emby for LG",
                "started_at": f"{today}T22:00:00",
                "stopped_at": f"{today}T23:00:00",
                "duration_seconds": 3600,
            },
        )

        r = await client.get("/api/stats-cards?days=365")

        assert r.status_code == 200
        assert 'data-img="/api/img/user/u1?name=Alice"' in r.text
        assert 'data-icon="Movie"' in r.text
        assert 'data-icon="Episode"' in r.text
        assert 'data-icon="Emby Web"' in r.text
        assert 'data-icon="Emby for LG"' in r.text

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
        await history_db.insert_history(
            db,
            {
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
            },
        )
        r = await client.get("/api/history-table")
        assert r.status_code == 200
        assert "expand-chevron" in r.text
        assert "detail-row" in r.text
        assert "Test Movie" in r.text
        assert "Alice" in r.text
        assert "history-row" in r.text

    @pytest.mark.asyncio
    async def test_stream_info_shows_transcode_reasons(self, client):
        db = client._test_db
        await history_db.insert_history(
            db,
            {
                "session_key": "s-reasons",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "m1",
                "item_name": "Test Movie",
                "item_type": "Movie",
                "play_method": "Transcode",
                "started_at": "2024-01-15T20:00:00",
                "stopped_at": "2024-01-15T22:00:00",
                "duration_seconds": 7200,
                "stream_info": json.dumps({
                    "video": {"codec": "HEVC", "height": 2160},
                    "transcode": {
                        "video_codec": "H264",
                        "reasons": ["VideoCodecNotSupported", "ContainerNotSupported"],
                    },
                }),
            },
        )
        cursor = await db.execute("SELECT id FROM history WHERE session_key = 's-reasons'")
        history_id = (await cursor.fetchone())["id"]

        r = await client.get(f"/api/stream-info/{history_id}")
        assert r.status_code == 200
        assert "Transcode Reasons" in r.text
        assert "Video codec not supported" in r.text
        assert "Container not supported" in r.text

    @pytest.mark.asyncio
    async def test_history_table_episode_links_to_series_page(self, client):
        db = client._test_db
        await history_db.insert_history(
            db,
            {
                "session_key": "ep-series-link",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "29865",
                "item_name": "Episode 5",
                "item_type": "Episode",
                "series_name": "Lead Children",
                "series_id": "38131",
                "season_number": 1,
                "episode_number": 5,
                "started_at": "2024-01-15T20:00:00",
                "stopped_at": "2024-01-15T21:00:00",
                "duration_seconds": 3600,
            },
        )

        r = await client.get("/api/history-table")

        assert r.status_code == 200
        assert "/item/38131?type=series&amp;name=Lead%20Children" in r.text

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
        await history_db.insert_history(
            db,
            {
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
            },
        )
        # Get the inserted record's id
        cursor = await db.execute(
            "SELECT id FROM history WHERE item_name = 'Another Movie'"
        )
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
        stream_info = json.dumps(
            {
                "video": {
                    "codec": "HEVC",
                    "width": 1920,
                    "height": 1080,
                    "bitrate": 5000000,
                },
                "audio": {"codec": "AAC", "channels": 6, "language": "english"},
                "media": {
                    "container": "MKV",
                    "bitrate": 5500000,
                    "resolution": "1080p",
                },
                "transcode": {"video_codec": "H264", "width": 1280, "height": 720},
            }
        )
        await history_db.insert_history(
            db,
            {
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
            },
        )
        cursor = await db.execute(
            "SELECT id FROM history WHERE item_name = 'Streamed Movie'"
        )
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
    async def test_export_history_csv(self, client):
        db = client._test_db
        await history_db.insert_history(
            db,
            {
                "session_key": "exp1",
                "user_id": "u1",
                "user_name": "Alice",
                "item_name": "Export Movie",
                "item_type": "Movie",
                "started_at": "2024-01-01T12:00:00",
                "stopped_at": "2024-01-01T14:00:00",
                "duration_seconds": 7200,
            },
        )
        r = await client.get("/api/export/history?format=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "Export Movie" in r.text
        assert "Alice" in r.text
        assert "started_at" in r.text  # header row

    @pytest.mark.asyncio
    async def test_export_history_json(self, client):
        db = client._test_db
        await history_db.insert_history(
            db,
            {
                "session_key": "exp2",
                "user_id": "u2",
                "user_name": "Bob",
                "item_name": "JSON Movie",
                "item_type": "Movie",
                "started_at": "2024-02-01T12:00:00",
                "stopped_at": "2024-02-01T14:00:00",
                "duration_seconds": 7200,
            },
        )
        r = await client.get("/api/export/history?format=json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        data = r.json()
        assert isinstance(data, list)
        assert any(row["item_name"] == "JSON Movie" for row in data)

    @pytest.mark.asyncio
    async def test_export_history_filtered(self, client):
        db = client._test_db
        await history_db.insert_history(
            db,
            {
                "session_key": "expf1",
                "user_id": "u1",
                "user_name": "Alice",
                "item_name": "Movie A",
                "item_type": "Movie",
                "started_at": "2024-03-01T12:00:00",
                "stopped_at": "2024-03-01T14:00:00",
            },
        )
        await history_db.insert_history(
            db,
            {
                "session_key": "expf2",
                "user_id": "u2",
                "user_name": "Bob",
                "item_name": "Episode B",
                "item_type": "Episode",
                "started_at": "2024-03-02T12:00:00",
                "stopped_at": "2024-03-02T14:00:00",
            },
        )
        r = await client.get("/api/export/history?format=csv&item_type=Movie")
        assert r.status_code == 200
        assert "Movie A" in r.text
        assert "Episode B" not in r.text

    @pytest.mark.asyncio
    async def test_delete_history(self, client):
        db = client._test_db
        await history_db.insert_history(
            db,
            {
                "session_key": "del1",
                "user_id": "u1",
                "item_name": "To Delete",
                "started_at": "2024-01-01T12:00:00",
                "stopped_at": "2024-01-01T14:00:00",
            },
        )
        cursor = await db.execute(
            "SELECT id FROM history WHERE item_name = 'To Delete'"
        )
        row = await cursor.fetchone()
        r = await client.delete(f"/api/history/{row[0]}")
        assert r.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_history_not_found(self, client):
        r = await client.delete("/api/history/99999")
        assert r.status_code == 404

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
        await history_db.insert_history(
            db,
            {
                "session_key": "chart1",
                "user_id": "u1",
                "item_type": "Movie",
                "started_at": f"{today}T12:00:00",
                "stopped_at": f"{today}T14:00:00",
                "duration_seconds": 7200,
            },
        )
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
    async def test_graphs_page(self, client):
        r = await client.get("/graphs")
        assert r.status_code == 200
        assert "g-daily-stacked" in r.text
        assert "<h2>Graphs</h2>" not in r.text

    @pytest.mark.asyncio
    async def test_item_detail_series_request_resolves_from_episode_id(self, client):
        class StubEmbyClient:
            async def get_item(self, item_id):
                if item_id == "29840":
                    return {
                        "Id": "29840",
                        "Name": "Episode 5",
                        "Type": "Episode",
                        "SeriesName": "Lead Children",
                        "SeriesId": "38131",
                        "ParentIndexNumber": 1,
                        "IndexNumber": 5,
                    }
                if item_id == "38131":
                    return {
                        "Id": "38131",
                        "Name": "Lead Children",
                        "Type": "Series",
                        "Overview": "Series overview",
                        "ProductionYear": 2026,
                        "Genres": ["Drama"],
                    }
                return {}

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get("/item/29840?type=series&name=Lead%20Children")

        assert r.status_code == 200
        assert "Series overview" in r.text
        assert "/api/img/38131?w=400" in r.text
        assert ">Lead Children<" in r.text

    @pytest.mark.asyncio
    async def test_chart_plays_by_dow(self, client):
        r = await client.get("/api/charts/plays-by-dow?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_plays_by_hour(self, client):
        r = await client.get("/api/charts/plays-by-hour?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_plays_per_month(self, client):
        r = await client.get("/api/charts/plays-per-month?months=12")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_plays_per_month_respects_days_filter(self, client):
        db = client._test_db
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=10)).date().isoformat()
        older = (now - timedelta(days=75)).date().isoformat()

        await history_db.insert_history(
            db,
            {
                "session_key": "month-recent",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "movie-recent",
                "item_name": "Recent Movie",
                "item_type": "Movie",
                "started_at": f"{recent}T20:00:00",
                "stopped_at": f"{recent}T22:00:00",
                "duration_seconds": 7200,
            },
        )
        await history_db.insert_history(
            db,
            {
                "session_key": "month-older",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "movie-older",
                "item_name": "Older Movie",
                "item_type": "Movie",
                "started_at": f"{older}T20:00:00",
                "stopped_at": f"{older}T22:00:00",
                "duration_seconds": 7200,
            },
        )

        recent_only = await client.get("/api/charts/plays-per-month?days=30")
        assert recent_only.status_code == 200
        assert sum(row["plays"] for row in recent_only.json()) == 1

        extended = await client.get("/api/charts/plays-per-month?days=120")
        assert extended.status_code == 200
        assert sum(row["plays"] for row in extended.json()) == 2

    @pytest.mark.asyncio
    async def test_chart_plays_by_date_stacked(self, client):
        r = await client.get("/api/charts/plays-by-date-stacked?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_plays_by_stream_type(self, client):
        r = await client.get("/api/charts/plays-by-stream-type?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_source_resolution(self, client):
        r = await client.get("/api/charts/source-resolution?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_transcode_ratio(self, client):
        r = await client.get("/api/charts/transcode-ratio?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_top_platforms_stream_type(self, client):
        r = await client.get("/api/charts/top-platforms-stream-type?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_top_users_stream_type(self, client):
        r = await client.get("/api/charts/top-users-stream-type?days=30")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_chart_period_comparison_uses_selected_window(self, client):
        db = client._test_db
        now = datetime.now(timezone.utc)
        current = (now - timedelta(days=5)).date().isoformat()
        previous = (now - timedelta(days=25)).date().isoformat()
        older = (now - timedelta(days=50)).date().isoformat()

        for session_key, day in [
            ("period-current", current),
            ("period-previous", previous),
            ("period-older", older),
        ]:
            await history_db.insert_history(
                db,
                {
                    "session_key": session_key,
                    "user_id": "u1",
                    "user_name": "Alice",
                    "item_id": session_key,
                    "item_name": session_key,
                    "item_type": "Movie",
                    "started_at": f"{day}T20:00:00",
                    "stopped_at": f"{day}T22:00:00",
                    "duration_seconds": 7200,
                },
            )

        r = await client.get("/api/charts/period-comparison?days=20")
        assert r.status_code == 200
        data = r.json()
        assert data["current"]["plays"] == 1
        assert data["previous"]["plays"] == 1

    @pytest.mark.asyncio
    async def test_recently_added_no_emby(self, client):
        r = await client.get("/api/recently-added")
        assert r.status_code == 200
        assert "No recently added" in r.text

    @pytest.mark.asyncio
    async def test_recently_added_episode_uses_series_poster_and_link(self, client):
        class StubEmbyClient:
            async def get_recently_added(self, limit=10, item_type=""):
                return [
                    {
                        "Id": "ep123",
                        "Name": "Episode 5",
                        "Type": "Episode",
                        "SeriesId": "series456",
                        "SeriesName": "Lead Children",
                        "ProductionYear": 2026,
                        "DateCreated": "2026-03-10T08:00:00Z",
                    }
                ]

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get("/api/recently-added")

        assert r.status_code == 200
        assert "/item/series456?type=series&amp;name=Lead%20Children" in r.text
        assert "/api/img/series456" in r.text
        assert "/api/img/ep123" not in r.text

    @pytest.mark.asyncio
    async def test_unwatched_api_filters_watched_shows(self, client):
        db = client._test_db
        today = datetime.now(timezone.utc).date().isoformat()
        await history_db.insert_history(
            db,
            {
                "session_key": "watched-show",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "ep1",
                "item_name": "Pilot",
                "item_type": "Episode",
                "series_name": "Severance",
                "series_id": "series-1",
                "started_at": f"{today}T20:00:00",
                "stopped_at": f"{today}T21:00:00",
            },
        )

        class StubEmbyClient:
            async def get_catalog_page(
                self,
                limit=100,
                start_index=0,
                search="",
                parent_id="",
                include_item_types="Series",
            ):
                assert include_item_types == "Movie,Series,Audio"
                return {
                    "items": [
                        {
                            "Id": "series-1",
                            "Name": "Severance",
                            "Type": "Series",
                            "ProductionYear": 2022,
                        },
                        {
                            "Id": "series-2",
                            "Name": "Andor",
                            "Type": "Series",
                            "ProductionYear": 2022,
                            "Overview": "Rebel spy thriller",
                        },
                    ],
                    "total": 2,
                }

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get("/api/unwatched")

        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert data["shown"] == 1
        assert data["items"][0]["item_id"] == "series-2"
        assert data["items"][0]["name"] == "Andor"

    @pytest.mark.asyncio
    async def test_unwatched_table_partial_uses_compact_rows(self, client):
        class StubEmbyClient:
            async def get_catalog_page(
                self,
                limit=100,
                start_index=0,
                search="",
                parent_id="",
                include_item_types="Series",
            ):
                return {
                    "items": [
                        {
                            "Id": "series-2",
                            "Name": "Andor",
                            "Type": "Series",
                            "ProductionYear": 2022,
                            "Overview": "Rebel spy thriller",
                            "PremiereDate": "2022-09-21T00:00:00Z",
                            "DateCreated": "2026-03-12T10:00:00Z",
                        }
                    ],
                    "total": 1,
                }

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get("/api/unwatched-table")

        assert r.status_code == 200
        assert "<table" in r.text
        assert "Andor" in r.text
        assert "No playback history yet." not in r.text

    @pytest.mark.asyncio
    async def test_unwatched_api_deduplicates_same_title_with_multiple_ids(
        self, client
    ):
        class StubEmbyClient:
            async def get_catalog_page(
                self,
                limit=100,
                start_index=0,
                search="",
                parent_id="",
                include_item_types="Series",
            ):
                return {
                    "items": [
                        {
                            "Id": "movie-1",
                            "Name": "28 Years Later",
                            "Type": "Movie",
                            "ProductionYear": 2025,
                            "PremiereDate": "2025-06-17T00:00:00Z",
                            "DateCreated": "2026-02-20T00:00:00Z",
                            "Overview": "",
                        },
                        {
                            "Id": "movie-2",
                            "Name": "28 Years Later",
                            "Type": "Movie",
                            "ProductionYear": 2025,
                            "PremiereDate": "2025-06-17T00:00:00Z",
                            "DateCreated": "2026-02-20T00:00:00Z",
                            "Overview": "A richer overview",
                        },
                    ],
                    "total": 2,
                }

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get("/api/unwatched")

        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "28 Years Later"
        assert data["items"][0]["overview"] == "A richer overview"

    @pytest.mark.asyncio
    async def test_unwatched_api_filters_seen_titles_with_normalized_name(self, client):
        db = client._test_db
        today = datetime.now(timezone.utc).date().isoformat()
        await history_db.insert_history(
            db,
            {
                "session_key": "seen-series-normalized",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "ep1",
                "item_name": "Episode 1",
                "item_type": "Episode",
                "series_name": "S.W.A.T.",
                "series_id": "series-1",
                "started_at": f"{today}T20:00:00",
                "stopped_at": f"{today}T21:00:00",
            },
        )

        class StubEmbyClient:
            async def get_catalog_page(
                self,
                limit=100,
                start_index=0,
                search="",
                parent_id="",
                include_item_types="Series",
            ):
                return {
                    "items": [
                        {
                            "Id": "series-2",
                            "Name": "SWAT",
                            "Type": "Series",
                            "ProductionYear": 2017,
                        }
                    ],
                    "total": 1,
                }

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get("/api/unwatched")

        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_unwatched_api_supports_pagination_sort_and_library_filter(
        self, client
    ):
        db = client._test_db
        await libraries_db.upsert_library(
            db,
            {
                "emby_library_id": "tv-lib-2",
                "name": "Drama",
                "library_type": "tvshows",
                "item_count": 3,
            },
        )

        class StubEmbyClient:
            async def get_catalog_page(
                self,
                limit=100,
                start_index=0,
                search="",
                parent_id="",
                include_item_types="Series",
            ):
                assert parent_id == "tv-lib-2"
                assert include_item_types == "Series"
                return {
                    "items": [
                        {
                            "Id": "series-a",
                            "Name": "Dark",
                            "Type": "Series",
                            "ProductionYear": 2017,
                            "DateCreated": "2026-03-10T08:00:00Z",
                        },
                        {
                            "Id": "series-b",
                            "Name": "Andor",
                            "Type": "Series",
                            "ProductionYear": 2022,
                            "DateCreated": "2026-03-11T08:00:00Z",
                        },
                        {
                            "Id": "series-c",
                            "Name": "Bodies",
                            "Type": "Series",
                            "ProductionYear": 2023,
                            "DateCreated": "2026-03-12T08:00:00Z",
                        },
                    ],
                    "total": 3,
                }

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get(
            "/api/unwatched?library_id=tv-lib-2&sort=name_asc&page=2&page_size=1"
        )

        assert r.status_code == 200
        data = r.json()
        assert data["library_id"] == "tv-lib-2"
        assert data["sort"] == "name_asc"
        assert data["total"] == 3
        assert data["total_pages"] == 3
        assert data["page"] == 2
        assert data["shown"] == 1
        assert data["items"][0]["name"] == "Bodies"

    @pytest.mark.asyncio
    async def test_unwatched_movies_library_uses_movie_catalog_and_empty_label(
        self, client
    ):
        db = client._test_db
        await libraries_db.upsert_library(
            db,
            {
                "emby_library_id": "movie-lib-2",
                "name": "Films",
                "library_type": "movies",
                "item_count": 1,
            },
        )
        today = datetime.now(timezone.utc).date().isoformat()
        await history_db.insert_history(
            db,
            {
                "session_key": "watched-movie",
                "user_id": "u1",
                "user_name": "Alice",
                "item_id": "movie-1",
                "item_name": "Arrival",
                "item_type": "Movie",
                "started_at": f"{today}T20:00:00",
                "stopped_at": f"{today}T22:00:00",
            },
        )

        class StubEmbyClient:
            async def get_catalog_page(
                self,
                limit=100,
                start_index=0,
                search="",
                parent_id="",
                include_item_types="Series",
            ):
                assert parent_id == "movie-lib-2"
                assert include_item_types == "Movie"
                return {
                    "items": [
                        {
                            "Id": "movie-1",
                            "Name": "Arrival",
                            "Type": "Movie",
                            "ProductionYear": 2016,
                        }
                    ],
                    "total": 1,
                }

        client._test_app.state.emby_client = StubEmbyClient()

        r = await client.get("/api/unwatched-table?library_id=movie-lib-2")

        assert r.status_code == 200
        assert "No unwatched movie found" in r.text
        assert "Every movie in Films already appears in playback history." in r.text

    @pytest.mark.asyncio
    async def test_manual_update_check_renders_status(self, client):
        class StubChecker:
            def __init__(self):
                self.info = UpdateInfo(current_version="0.2.1")

            async def check_once(self):
                self.info = UpdateInfo(
                    update_available=True,
                    latest_version="0.2.3",
                    current_version="0.2.1",
                    release_url="https://github.com/empul-dev/empulse/releases/tag/v0.2.3",
                    last_checked_at="2026-03-10T09:00:00+00:00",
                )
                return self.info

        client._test_app.state.update_checker = StubChecker()

        r = await client.post("/api/update-check")

        assert r.status_code == 200
        assert "Update available: v0.2.3" in r.text
        assert "Current version: v0.2.1" in r.text

    @pytest.mark.asyncio
    async def test_notification_channels_crud(self, client):
        # Create
        r = await client.post(
            "/api/notification-channels",
            json={
                "name": "Test Discord",
                "channel_type": "discord",
                "config": {"url": "https://discord.com/api/webhooks/test"},
                "triggers": ["playback_start", "playback_stop"],
                "conditions": {},
                "enabled": True,
            },
        )
        assert r.status_code == 201

        # List
        r = await client.get("/api/notification-channels")
        assert r.status_code == 200
        channels = r.json()
        assert len(channels) >= 1
        ch_id = channels[0]["id"]
        assert channels[0]["name"] == "Test Discord"

        # Update
        r = await client.put(
            f"/api/notification-channels/{ch_id}",
            json={
                "name": "Updated Discord",
                "channel_type": "discord",
                "config": {"url": "https://discord.com/api/webhooks/test"},
                "triggers": ["playback_start"],
                "conditions": {},
                "enabled": True,
            },
        )
        assert r.status_code == 200

        # Delete
        r = await client.delete(f"/api/notification-channels/{ch_id}")
        assert r.status_code == 204

    @pytest.mark.asyncio
    async def test_notification_channels_not_found(self, client):
        r = await client.put(
            "/api/notification-channels/99999",
            json={
                "name": "X",
                "channel_type": "discord",
                "config": {},
                "triggers": [],
                "conditions": {},
            },
        )
        assert r.status_code == 404
        r = await client.delete("/api/notification-channels/99999")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_notification_log(self, client):
        r = await client.get("/api/notification-log")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_settings_notifications_page(self, client):
        r = await client.get("/settings/notifications")
        assert r.status_code == 200
        assert "Notification" in r.text

    # --- Phase 3: Map, Newsletter, Locations ---

    @pytest.mark.asyncio
    async def test_newsletter_config_crud(self, client):
        # Initially empty
        r = await client.get("/api/newsletter/config")
        assert r.status_code == 200
        assert r.json() == {}

        # Save config
        r = await client.post(
            "/api/newsletter/config",
            json={
                "enabled": True,
                "schedule": "weekly",
                "day_of_week": 1,
                "hour": 10,
                "recently_added_days": 7,
                "recently_added_limit": 15,
                "include_stats": True,
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "user@example.com",
                "smtp_pass": "pass",
                "smtp_tls": True,
                "from_addr": "empulse@example.com",
                "to_addrs": "admin@example.com",
            },
        )
        assert r.status_code == 200

        # Read back
        r = await client.get("/api/newsletter/config")
        assert r.status_code == 200
        config = r.json()
        assert config["enabled"] == 1
        assert config["schedule"] == "weekly"
        assert config["smtp_host"] == "smtp.example.com"

        # Update
        r = await client.post(
            "/api/newsletter/config",
            json={
                "enabled": False,
                "schedule": "daily",
                "day_of_week": 0,
                "hour": 8,
                "recently_added_days": 3,
                "recently_added_limit": 10,
                "include_stats": False,
                "smtp_host": "mail.example.com",
                "smtp_port": 465,
                "smtp_user": "",
                "smtp_pass": "",
                "smtp_tls": False,
                "from_addr": "",
                "to_addrs": "",
            },
        )
        assert r.status_code == 200
        r = await client.get("/api/newsletter/config")
        assert r.json()["schedule"] == "daily"

    @pytest.mark.asyncio
    async def test_newsletter_preview(self, client):
        r = await client.get("/api/newsletter/preview")
        assert r.status_code == 200
        assert "Empulse Newsletter" in r.text

    @pytest.mark.asyncio
    async def test_newsletter_send_not_configured(self, client):
        r = await client.post("/api/newsletter/send")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_settings_newsletter_page(self, client):
        r = await client.get("/settings/newsletter")
        assert r.status_code == 200
        assert "Newsletter" in r.text

    @pytest.mark.asyncio
    async def test_static_css(self, client):
        r = await client.get("/static/css/style.css")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_static_js(self, client):
        r = await client.get("/static/js/app.js")
        assert r.status_code == 200
        assert "WebSocket" in r.text


class TestSettingsViewNoSecretLeak:
    """I-2: the settings page must never receive secret values in its context."""

    @pytest.mark.asyncio
    async def test_settings_view_whitelist_only(self):
        from types import SimpleNamespace
        from empulse.web.router import SettingsView

        fake = SimpleNamespace(
            emby_url="http://localhost:8096",
            poll_interval=15,
            emby_api_key="super-secret-key",
            secret_key="top-secret-hmac",
            auth_password="hunter2",
        )
        with patch("empulse.web.router.settings", fake):
            view = SettingsView.from_settings()

        assert view.emby_url == "http://localhost:8096"
        assert view.poll_interval == 15
        assert view.has_api_key is True
        # No secret ever survives onto the view object.
        for secret in ("super-secret-key", "top-secret-hmac", "hunter2"):
            assert secret not in repr(view)
        for attr in ("emby_api_key", "secret_key", "auth_password"):
            assert not hasattr(view, attr)

    @pytest.mark.asyncio
    async def test_settings_page_omits_secrets(self, client):
        from types import SimpleNamespace

        fake = SimpleNamespace(
            emby_url="http://localhost:8096",
            poll_interval=10,
            emby_api_key="super-secret-key",
            secret_key="top-secret-hmac",
            auth_password="hunter2",
        )
        with patch("empulse.web.router.settings", fake):
            r = await client.get("/settings")

        assert r.status_code == 200
        assert "super-secret-key" not in r.text
        assert "top-secret-hmac" not in r.text
        assert "hunter2" not in r.text
        assert "••••••••" in r.text  # masked key shown


class TestEmbyUrlValidation:
    """A4 (S-2, E-4): refuse boot on an unsafe EMBY_URL, allow LAN/loopback."""

    def _run(self, url, *, resolves_to=None, allow_insecure=False, allow_private=False):
        """Validate `url`, patching DNS resolution to `resolves_to` (list of IP
        strings, or None to force an unresolvable host) so tests never hit the
        network."""
        import ipaddress
        from types import SimpleNamespace
        from empulse.emby import client as emby_client

        fake = SimpleNamespace(
            emby_url=url,
            emby_allow_insecure=allow_insecure,
            emby_allow_private=allow_private,
        )
        ips = [ipaddress.ip_address(ip) for ip in (resolves_to or [])]
        with (
            patch.object(emby_client, "settings", fake),
            patch.object(emby_client, "_resolve_ips", return_value=ips),
        ):
            emby_client.validate_emby_url()

    def test_loopback_http_allowed(self):
        self._run("http://localhost:8096", resolves_to=["127.0.0.1"])
        self._run("http://127.0.0.1:8096", resolves_to=["127.0.0.1"])

    def test_private_lan_http_allowed(self):
        # RFC1918 LAN over plain HTTP is the normal self-hosted case.
        self._run("http://192.168.1.50:8096", resolves_to=["192.168.1.50"])

    def test_public_https_allowed(self):
        self._run("https://emby.example.com", resolves_to=["93.184.216.34"])

    def test_public_http_refused(self):
        with pytest.raises(RuntimeError, match="unencrypted"):
            self._run("http://emby.example.com", resolves_to=["93.184.216.34"])

    def test_public_http_override(self):
        self._run("http://emby.example.com", resolves_to=["93.184.216.34"], allow_insecure=True)

    def test_metadata_ip_refused(self):
        with pytest.raises(RuntimeError, match="link-local"):
            self._run("http://169.254.169.254", resolves_to=["169.254.169.254"])

    def test_metadata_hostname_refused(self):
        # Classic SSRF bypass: a benign-looking name resolving to the metadata IP.
        with pytest.raises(RuntimeError, match="link-local"):
            self._run("http://metadata.internal", resolves_to=["169.254.169.254"])

    def test_metadata_ip_override(self):
        self._run("http://169.254.169.254", resolves_to=["169.254.169.254"], allow_private=True)

    def test_unresolvable_host_is_lenient(self):
        # DNS not ready at container start must not block a legit start-up.
        self._run("http://emby-that-does-not-resolve.invalid:8096", resolves_to=None)
