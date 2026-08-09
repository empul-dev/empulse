import json

import pytest

from empulse.db import history as history_db, users as users_db, libraries as libraries_db, stats as stats_db


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


    @pytest.mark.asyncio
    async def test_get_history_by_id(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "m1",
            "item_name": "Test Movie",
            "item_type": "Movie",
            "started_at": "2024-01-01T12:00:00",
            "stopped_at": "2024-01-01T14:00:00",
            "duration_seconds": 7200,
        })

        # Fetch all to get the id
        rows = await history_db.get_history(db)
        record_id = rows[0]["id"]

        result = await history_db.get_history_by_id(db, record_id)
        assert result is not None
        assert result["item_name"] == "Test Movie"
        assert result["user_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_history_by_id_not_found(self, db):
        result = await history_db.get_history_by_id(db, 99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_find_recent_history(self, db):
        from datetime import datetime, timezone, timedelta
        recent_stop = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "item_id": "m1",
            "item_name": "Recent Movie",
            "started_at": "2024-01-01T12:00:00",
            "stopped_at": recent_stop,
            "duration_seconds": 1800,
        })

        result = await history_db.find_recent_history(db, "u1", "m1")
        assert result is not None
        assert result["item_name"] == "Recent Movie"

    @pytest.mark.asyncio
    async def test_find_recent_history_too_old(self, db):
        from datetime import datetime, timezone, timedelta
        old_stop = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "item_id": "m1",
            "item_name": "Old Movie",
            "started_at": "2024-01-01T12:00:00",
            "stopped_at": old_stop,
            "duration_seconds": 1800,
        })

        result = await history_db.find_recent_history(db, "u1", "m1")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_recent_history_wrong_user(self, db):
        from datetime import datetime, timezone, timedelta
        recent_stop = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "item_id": "m1",
            "item_name": "Movie",
            "started_at": "2024-01-01T12:00:00",
            "stopped_at": recent_stop,
            "duration_seconds": 1800,
        })

        result = await history_db.find_recent_history(db, "u2", "m1")
        assert result is None

    @pytest.mark.asyncio
    async def test_merge_history(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "item_id": "m1",
            "item_name": "Movie",
            "started_at": "2024-01-01T12:00:00",
            "stopped_at": "2024-01-01T13:00:00",
            "duration_seconds": 3600,
            "paused_seconds": 60,
            "percent_complete": 50.0,
            "watched": 0,
            "progress_ticks": 36000000000,
        })

        rows = await history_db.get_history(db)
        record_id = rows[0]["id"]

        await history_db.merge_history(db, record_id, {
            "stopped_at": "2024-01-01T14:00:00",
            "duration_seconds": 7200,
            "paused_seconds": 120,
            "percent_complete": 95.0,
            "watched": 1,
            "progress_ticks": 72000000000,
            "stream_info": '{"video": {"codec": "H264"}}',
        })

        updated = await history_db.get_history_by_id(db, record_id)
        assert updated["stopped_at"] == "2024-01-01T14:00:00"
        assert updated["duration_seconds"] == 7200
        assert updated["paused_seconds"] == 120
        assert updated["percent_complete"] == 95.0
        assert updated["watched"] == 1
        assert updated["progress_ticks"] == 72000000000


    @pytest.mark.asyncio
    async def test_delete_history(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1",
            "user_id": "u1",
            "item_name": "To Delete",
            "started_at": "2024-01-01T12:00:00",
            "stopped_at": "2024-01-01T14:00:00",
        })
        rows = await history_db.get_history(db)
        record_id = rows[0]["id"]

        deleted = await history_db.delete_history(db, record_id)
        assert deleted is True

        result = await history_db.get_history_by_id(db, record_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_history_not_found(self, db):
        deleted = await history_db.delete_history(db, 99999)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_migrate_nulls_garbage_framerate(self, db):
        from empulse.database import _migrate

        # Garbage fps (>240) gets nulled; plausible fps is left intact.
        bad = {"video": {"framerate": 24.0}, "transcode": {"framerate": 5792.0}}
        ok = {"video": {"framerate": 24.0}, "transcode": {"framerate": 24.0}}
        id_bad = await history_db.insert_history_returning_id(db, {
            "session_key": "b", "user_id": "u", "user_name": "A", "item_id": "i",
            "item_name": "Bad", "item_type": "Movie", "started_at": "2024-01-01T00:00:00",
            "stopped_at": "2024-01-01T01:00:00", "duration_seconds": 3600,
            "stream_info": json.dumps(bad),
        })
        id_ok = await history_db.insert_history_returning_id(db, {
            "session_key": "g", "user_id": "u", "user_name": "A", "item_id": "i",
            "item_name": "Ok", "item_type": "Movie", "started_at": "2024-01-01T00:00:00",
            "stopped_at": "2024-01-01T01:00:00", "duration_seconds": 3600,
            "stream_info": json.dumps(ok),
        })

        await _migrate(db)

        got_bad = json.loads((await history_db.get_history_by_id(db, id_bad))["stream_info"])
        got_ok = json.loads((await history_db.get_history_by_id(db, id_ok))["stream_info"])
        assert got_bad["transcode"]["framerate"] is None
        assert got_ok["transcode"]["framerate"] == 24.0


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
    async def test_stats_derived_from_history(self, db):
        # Totals come from counted_plays (history rows >= MIN_PLAY_SECONDS),
        # not the drift-prone counter columns.
        await users_db.upsert_user(db, {
            "emby_user_id": "u1", "username": "Alice",
            "is_admin": 0, "thumb_url": None, "last_seen": None,
        })
        for i, dur in enumerate([3600, 1800, 60]):  # 60s is below the 600s cutoff
            await history_db.insert_history(db, {
                "session_key": f"s{i}", "user_id": "u1", "user_name": "Alice",
                "item_name": f"Item{i}",
                "started_at": f"2024-01-0{i+1}T12:00:00",
                "stopped_at": f"2024-01-0{i+1}T14:00:00",
                "duration_seconds": dur,
            })

        user = await users_db.get_user(db, "u1")
        assert user["total_plays"] == 2          # 60s play excluded
        assert user["total_duration"] == 5400

    @pytest.mark.asyncio
    async def test_get_all_sorted_by_plays(self, db):
        for name, plays in [("Alice", 10), ("Bob", 20), ("Charlie", 5)]:
            await users_db.upsert_user(db, {
                "emby_user_id": name.lower(), "username": name,
                "is_admin": 0, "thumb_url": None, "last_seen": None,
            })
            for i in range(plays):
                await history_db.insert_history(db, {
                    "session_key": f"{name}-{i}", "user_id": name.lower(),
                    "user_name": name, "item_name": f"Item{i}",
                    "started_at": "2024-01-01T12:00:00",
                    "stopped_at": "2024-01-01T14:00:00",
                    "duration_seconds": 3600,
                })

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
    async def test_upsert_stores_child_count(self, db):
        await libraries_db.upsert_library(db, {
            "emby_library_id": "tv1", "name": "TV shows",
            "library_type": "tvshows", "item_count": 587, "child_count": 12577,
        })
        libs = await libraries_db.get_all_libraries(db)
        assert libs[0]["item_count"] == 587
        assert libs[0]["child_count"] == 12577

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
    async def test_plays_by_type(self, db):
        await history_db.insert_history(db, {
            "session_key": "s1", "item_type": "Movie",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
            "duration_seconds": 7200,
        })
        await history_db.insert_history(db, {
            "session_key": "s2", "item_type": "Episode",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
            "duration_seconds": 7200,
        })
        await history_db.insert_history(db, {
            "session_key": "s3", "item_type": "Episode",
            "started_at": "2024-01-01T12:00:00", "stopped_at": "2024-01-01T14:00:00",
            "duration_seconds": 7200,
        })

        by_type = await stats_db.get_plays_by_type(db, days=99999)
        types = {r["item_type"]: r["plays"] for r in by_type}
        assert types["Episode"] == 2
        assert types["Movie"] == 1

    @pytest.mark.asyncio
    async def test_user_plays_per_day(self, db):
        from datetime import date
        today = date.today().isoformat()
        await history_db.insert_history(db, {
            "session_key": "s1", "user_id": "u1", "user_name": "Alice",
            "item_type": "Movie",
            "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
            "duration_seconds": 7200,
        })
        rows = await stats_db.get_user_plays_per_day(db, "u1", days=7)
        assert any(r["plays"] == 1 for r in rows)

    @pytest.mark.asyncio
    async def test_user_most_watched(self, db):
        from datetime import date
        today = date.today().isoformat()
        for i in range(3):
            await history_db.insert_history(db, {
                "session_key": f"s{i}", "user_id": "u1", "user_name": "Alice",
                "item_id": "m1", "item_name": "Popular Movie", "item_type": "Movie",
                "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
                "duration_seconds": 7200,
            })
        top = await stats_db.get_user_most_watched(db, "u1", limit=5, days=99999)
        assert len(top) >= 1
        assert top[0]["title"] == "Popular Movie"
        assert top[0]["plays"] == 3

    @pytest.mark.asyncio
    async def test_show_aggregations_prefer_latest_non_empty_series_id(self, db):
        from datetime import date

        today = date.today().isoformat()
        await history_db.insert_history(db, {
            "session_key": "show-old",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "25450",
            "item_name": "Pilot",
            "item_type": "Episode",
            "series_name": "The Pitt",
            "series_id": "",
            "started_at": f"{today}T12:00:00",
            "stopped_at": f"{today}T13:00:00",
            "duration_seconds": 1800,
        })
        await history_db.insert_history(db, {
            "session_key": "show-new",
            "user_id": "u2",
            "user_name": "Bob",
            "item_id": "25451",
            "item_name": "Episode 2",
            "item_type": "Episode",
            "series_name": "The Pitt",
            "series_id": "35974",
            "started_at": f"{today}T14:00:00",
            "stopped_at": f"{today}T15:00:00",
            "duration_seconds": 1800,
        })

        watched = await stats_db.get_most_watched_shows(db, limit=5, days=99999)
        popular = await stats_db.get_most_popular_shows(db, limit=5, days=99999)
        user_top = await stats_db.get_user_most_watched(db, "u2", limit=5, days=99999)
        library_top = await stats_db.get_library_top_items(db, "Episode", limit=5, days=99999)

        assert watched[0]["poster_id"] == "35974"
        assert popular[0]["poster_id"] == "35974"
        assert user_top[0]["poster_id"] == "35974"
        assert library_top[0]["poster_id"] == "35974"

    @pytest.mark.asyncio
    async def test_get_watched_series_keys(self, db):
        from datetime import date

        today = date.today().isoformat()
        await history_db.insert_history(db, {
            "session_key": "show-keys-1",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "ep1",
            "item_name": "Pilot",
            "item_type": "Episode",
            "series_name": "Severance",
            "series_id": "series-1",
            "started_at": f"{today}T12:00:00",
            "stopped_at": f"{today}T13:00:00",
        })
        await history_db.insert_history(db, {
            "session_key": "show-keys-2",
            "user_id": "u2",
            "user_name": "Bob",
            "item_id": "ep2",
            "item_name": "Episode 2",
            "item_type": "Episode",
            "series_name": "Severance",
            "series_id": "",
            "started_at": f"{today}T14:00:00",
            "stopped_at": f"{today}T15:00:00",
        })

        watched = await stats_db.get_watched_series_keys(db)

        assert watched["series_ids"] == {"series-1"}
        assert watched["series_names"] == {"Severance"}

    @pytest.mark.asyncio
    async def test_library_top_items(self, db):
        from datetime import date
        today = date.today().isoformat()
        for i in range(3):
            await history_db.insert_history(db, {
                "session_key": f"s{i}", "user_id": "u1",
                "item_id": "m1", "item_name": "Top Movie", "item_type": "Movie",
                "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
                "duration_seconds": 7200,
            })
        top = await stats_db.get_library_top_items(db, "Movie", limit=5, days=99999)
        assert len(top) >= 1
        assert top[0]["title"] == "Top Movie"

    @pytest.mark.asyncio
    async def test_user_plays_by_type(self, db):
        from datetime import date
        today = date.today().isoformat()
        await history_db.insert_history(db, {
            "session_key": "s1", "user_id": "u1", "item_type": "Movie",
            "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
            "duration_seconds": 7200,
        })
        await history_db.insert_history(db, {
            "session_key": "s2", "user_id": "u1", "item_type": "Episode",
            "started_at": f"{today}T15:00:00", "stopped_at": f"{today}T16:00:00",
            "duration_seconds": 3600,
        })
        rows = await stats_db.get_user_plays_by_type(db, "u1", days=99999)
        types = {r["item_type"]: r["plays"] for r in rows}
        assert types["Movie"] == 1
        assert types["Episode"] == 1

    @pytest.mark.asyncio
    async def test_library_stats(self, db):
        from datetime import date
        today = date.today().isoformat()
        for i in range(3):
            await history_db.insert_history(db, {
                "session_key": f"ls{i}", "user_id": f"u{i}", "item_type": "Movie",
                "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
                "duration_seconds": 3600,
            })
        stats = await stats_db.get_library_stats(db, "Movie")
        assert stats["all_time"]["plays"] == 3
        assert stats["all_time"]["users"] == 3
        assert stats["all_time"]["duration"] == 10800

    @pytest.mark.asyncio
    async def test_library_plays_per_day(self, db):
        from datetime import date
        today = date.today().isoformat()
        await history_db.insert_history(db, {
            "session_key": "lpd1", "item_type": "Movie",
            "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
            "duration_seconds": 7200,
        })
        rows = await stats_db.get_library_plays_per_day(db, "Movie", days=7)
        assert any(r["plays"] == 1 for r in rows)

    @pytest.mark.asyncio
    async def test_library_top_users(self, db):
        from datetime import date
        today = date.today().isoformat()
        for i in range(5):
            await history_db.insert_history(db, {
                "session_key": f"s{i}", "user_id": "u1", "user_name": "Alice",
                "item_type": "Movie",
                "started_at": f"{today}T12:00:00", "stopped_at": f"{today}T14:00:00",
                "duration_seconds": 7200,
            })
        top = await stats_db.get_library_top_users(db, "Movie", limit=5, days=99999)
        assert len(top) >= 1
        assert top[0]["user_name"] == "Alice"
        assert top[0]["plays"] == 5


class TestLegacySecretMigration:
    """I-1: plaintext notification/newsletter secrets get encrypted on boot."""

    @pytest.mark.asyncio
    async def test_encrypts_plaintext_channel_secret(self, db):
        from datetime import datetime, timezone

        from empulse.database import _migrate

        await db.execute(
            "INSERT INTO notification_channels (name, channel_type, config, triggers, conditions, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                "Legacy Telegram", "telegram",
                '{"bot_token": "plaintext-token", "chat_id": "1"}',
                "[]", "{}", 1, datetime.now(timezone.utc).isoformat(),
            ],
        )
        await db.commit()

        await _migrate(db)

        cursor = await db.execute("SELECT config FROM notification_channels")
        row = await cursor.fetchone()
        assert "plaintext-token" not in row["config"]
        assert "enc:v1:" in row["config"]

    @pytest.mark.asyncio
    async def test_encrypts_plaintext_newsletter_password(self, db):
        from empulse.database import _migrate

        await db.execute(
            "INSERT INTO newsletter_config (id, smtp_pass) VALUES (1, ?)",
            ["plaintext-smtp-pass"],
        )
        await db.commit()

        await _migrate(db)

        cursor = await db.execute("SELECT smtp_pass FROM newsletter_config WHERE id = 1")
        row = await cursor.fetchone()
        assert row["smtp_pass"] != "plaintext-smtp-pass"
        assert row["smtp_pass"].startswith("enc:v1:")

    @pytest.mark.asyncio
    async def test_migration_is_idempotent_on_already_encrypted_secrets(self, db):
        from datetime import datetime, timezone

        from empulse.crypto import encrypt_secret
        from empulse.database import _migrate

        already_encrypted = encrypt_secret("hunter2")
        await db.execute(
            "INSERT INTO notification_channels (name, channel_type, config, triggers, conditions, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                "Already Encrypted", "telegram",
                json.dumps({"bot_token": already_encrypted, "chat_id": "1"}),
                "[]", "{}", 1, datetime.now(timezone.utc).isoformat(),
            ],
        )
        await db.commit()

        await _migrate(db)

        cursor = await db.execute("SELECT config FROM notification_channels")
        row = await cursor.fetchone()
        stored = json.loads(row["config"])
        assert stored["bot_token"] == already_encrypted  # unchanged, not double-encrypted
