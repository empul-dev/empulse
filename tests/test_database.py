import pytest
import pytest_asyncio

from emtulli.db import history as history_db, users as users_db, libraries as libraries_db, stats as stats_db


class TestHistoryCRUD:
    @pytest.mark.asyncio
    async def test_insert_and_get(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "i1",
            "item_name": "Test Movie",
            "item_type": "Movie",
            "started_at": "2024-01-01T12:00:00",
            "stopped_at": "2024-01-01T14:00:00",
            "duration_seconds": 7200,
            "percent_complete": 95.0,
            "watched": 1,
        })

        rows = await history_db.get_history(db)
        assert len(rows) == 1
        assert rows[0]["user_name"] == "Alice"
        assert rows[0]["item_name"] == "Test Movie"

    @pytest.mark.asyncio
    async def test_filter_by_user(self, db):
        for i, uid in enumerate(["u1", "u1", "u2"]):
            await history_db.insert_history(db, {
                "session_key": f"s{i}",
                "user_id": uid,
                "user_name": f"User{uid}",
                "item_name": f"Item{i}",
                "started_at": f"2024-01-0{i+1}T12:00:00",
                "stopped_at": f"2024-01-0{i+1}T14:00:00",
            })

        rows = await history_db.get_history(db, user_id="u1")
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_filter_by_type(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1", "item_type": "Movie",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
        })
        await history_db.insert_history(db, {
            "session_key": "s2", "item_type": "Episode",
            "started_at": "2024-01-02T12:00:00", "stopped_at": "2024-01-02T14:00:00",
        })

        rows = await history_db.get_history(db, item_type="Movie")
        assert len(rows) == 1
        assert rows[0]["item_type"] == "Movie"

    @pytest.mark.asyncio
    async def test_search(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1", "item_name": "Breaking Bad",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
        })
        await history_db.insert_history(db, {
            "session_key": "s2", "item_name": "The Office",
            "started_at": "2024-01-02T12:00:00", "stopped_at": "2024-01-02T14:00:00",
        })

        rows = await history_db.get_history(db, search="Breaking")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_count(self, db):
        for i in range(5):
            await history_db.insert_history(db, {
                "session_key": f"s{i}",
                "started_at": "2024-01-01T12:00:00",
                "stopped_at": "2024-01-01T14:00:00",
            })

        count = await history_db.get_history_count(db)
        assert count == 5

    @pytest.mark.asyncio
    async def test_pagination(self, db):
        for i in range(10):
            await history_db.insert_history(db, {
                "session_key": f"s{i}",
                "started_at": f"2024-01-{i+1:02d}T12:00:00",
                "stopped_at": f"2024-01-{i+1:02d}T14:00:00",
            })

        page1 = await history_db.get_history(db, limit=3, offset=0)
        page2 = await history_db.get_history(db, limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0]["session_key"] != page2[0]["session_key"]


class TestUsersCRUD:
    @pytest.mark.asyncio
    async def test_upsert_and_get(self, db):
        await users_db.upsert_user(db, {
            "emby_user_id": "u1",
            "username": "Alice",
            "is_admin": 1,
            "thumb_url": None,
            "last_seen": None,
        })

        user = await users_db.get_user(db, "u1")
        assert user is not None
        assert user["username"] == "Alice"
        assert user["is_admin"] == 1

    @pytest.mark.asyncio
    async def test_upsert_updates(self, db):
        await users_db.upsert_user(db, {
            "emby_user_id": "u1", "username": "Alice",
            "is_admin": 0, "thumb_url": None, "last_seen": None,
        })
        await users_db.upsert_user(db, {
            "emby_user_id": "u1", "username": "Alice Updated",
            "is_admin": 1, "thumb_url": None, "last_seen": None,
        })

        user = await users_db.get_user(db, "u1")
        assert user["username"] == "Alice Updated"

    @pytest.mark.asyncio
    async def test_update_stats(self, db):
        await users_db.upsert_user(db, {
            "emby_user_id": "u1", "username": "Alice",
            "is_admin": 0, "thumb_url": None, "last_seen": None,
        })

        await users_db.update_user_stats(db, "u1", 3600)
        await users_db.update_user_stats(db, "u1", 1800)

        user = await users_db.get_user(db, "u1")
        assert user["total_plays"] == 2
        assert user["total_duration"] == 5400

    @pytest.mark.asyncio
    async def test_get_all_sorted_by_plays(self, db):
        for name, plays in [("Alice", 10), ("Bob", 20), ("Charlie", 5)]:
            await users_db.upsert_user(db, {
                "emby_user_id": name.lower(), "username": name,
                "is_admin": 0, "thumb_url": None, "last_seen": None,
            })
            for _ in range(plays):
                await users_db.update_user_stats(db, name.lower(), 60)

        users = await users_db.get_all_users(db)
        assert len(users) == 3
        assert users[0]["username"] == "Bob"

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, db):
        user = await users_db.get_user(db, "nonexistent")
        assert user is None


class TestLibrariesCRUD:
    @pytest.mark.asyncio
    async def test_upsert_and_get(self, db):
        await libraries_db.upsert_library(db, {
            "emby_library_id": "lib1",
            "name": "Movies",
            "library_type": "movies",
            "item_count": 150,
        })

        libs = await libraries_db.get_all_libraries(db)
        assert len(libs) == 1
        assert libs[0]["name"] == "Movies"
        assert libs[0]["item_count"] == 150

    @pytest.mark.asyncio
    async def test_upsert_updates_count(self, db):
        await libraries_db.upsert_library(db, {
            "emby_library_id": "lib1", "name": "Movies",
            "library_type": "movies", "item_count": 100,
        })
        await libraries_db.upsert_library(db, {
            "emby_library_id": "lib1", "name": "Movies",
            "library_type": "movies", "item_count": 200,
        })

        libs = await libraries_db.get_all_libraries(db)
        assert len(libs) == 1
        assert libs[0]["item_count"] == 200

    @pytest.mark.asyncio
    async def test_server_info(self, db):
        await libraries_db.upsert_server_info(db, {
            "server_name": "My Emby",
            "version": "4.8.0",
            "local_address": "http://192.168.1.10:8096",
            "wan_address": "http://public:8096",
            "os": "Linux",
        })

        info = await libraries_db.get_server_info(db)
        assert info is not None
        assert info["server_name"] == "My Emby"
        assert info["version"] == "4.8.0"


class TestStats:
    @pytest.mark.asyncio
    async def test_total_plays_empty(self, db):
        count = await stats_db.get_total_plays(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_total_plays(self, db):
        for i in range(3):
            await history_db.insert_history(db, {
                "session_key": f"s{i}",
                "started_at": "2024-01-01T12:00:00",
                "stopped_at": "2024-01-01T14:00:00",
                "duration_seconds": 3600,
            })

        assert await stats_db.get_total_plays(db) == 3
        assert await stats_db.get_total_duration(db) == 10800

    @pytest.mark.asyncio
    async def test_top_users(self, db):
        for i in range(5):
            await history_db.insert_history(db, {
                "session_key": f"a{i}", "user_id": "u1", "user_name": "Alice",
                "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
                "duration_seconds": 3600,
            })
        for i in range(2):
            await history_db.insert_history(db, {
                "session_key": f"b{i}", "user_id": "u2", "user_name": "Bob",
                "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
                "duration_seconds": 1800,
            })

        top = await stats_db.get_top_users(db, limit=10, days=99999)
        assert len(top) == 2
        assert top[0]["user_name"] == "Alice"
        assert top[0]["plays"] == 5

    @pytest.mark.asyncio
    async def test_most_played(self, db):
        for i in range(3):
            await history_db.insert_history(db, {
                "session_key": f"s{i}", "item_id": "movie1", "item_name": "Popular Movie",
                "item_type": "Movie",
                "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
            })
        await history_db.insert_history(db, {
            "session_key": "s99", "item_id": "movie2", "item_name": "Less Popular",
            "item_type": "Movie",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
        })

        top = await stats_db.get_most_played(db, limit=10)
        assert top[0]["item_name"] == "Popular Movie"
        assert top[0]["plays"] == 3

    @pytest.mark.asyncio
    async def test_plays_by_type(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1", "item_type": "Movie",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
        })
        await history_db.insert_history(db, {
            "session_key": "s2", "item_type": "Episode",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
        })
        await history_db.insert_history(db, {
            "session_key": "s3", "item_type": "Episode",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
        })

        by_type = await stats_db.get_plays_by_type(db)
        types = {r["item_type"]: r["plays"] for r in by_type}
        assert types["Episode"] == 2
        assert types["Movie"] == 1
