"""Keep update and restore operations isolated for the entire app lifetime."""

import asyncio
import sqlite3
import threading
from unittest.mock import AsyncMock

import pytest

from empulse import app as app_module, backups, database


@pytest.mark.parametrize("context_fails", [False, True])
async def test_lifespan_holds_lock_and_closes_resources(
    tmp_path, monkeypatch, context_fails
):
    from empulse.activity.poller import SessionPoller
    from empulse.emby.client import EmbyClient
    from empulse.emby.websocket import EmbyWebSocket
    from empulse.newsletter import NewsletterScheduler
    from empulse.update_checker import UpdateChecker
    from empulse.web.poster_cache import PosterWallCache

    db_path = tmp_path / "empulse.db"
    monkeypatch.setattr(database.settings, "db_path", str(db_path))
    monkeypatch.setattr(database.settings, "emby_url", "http://localhost:8096")
    monkeypatch.setattr(database.settings, "emby_api_key", "test-api-key")
    monkeypatch.setattr(database.settings, "disable_update_check", False)
    monkeypatch.setattr(database, "_db", None)
    client = AsyncMock(spec=EmbyClient)
    monkeypatch.setattr("empulse.emby.client.EmbyClient", lambda: client)
    services = [
        SessionPoller,
        EmbyWebSocket,
        NewsletterScheduler,
        UpdateChecker,
        PosterWallCache,
    ]
    started = {service: asyncio.Event() for service in services}
    stopped = {service: asyncio.Event() for service in services}
    running = []

    async def run(service):
        running.append(asyncio.current_task())
        started[type(service)].set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped[type(service)].set()

    for service in services:
        monkeypatch.setattr(service, "run", run)
    app = app_module.create_app()
    connection = None

    async def exercise_lifespan():
        nonlocal connection
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in started.values())), timeout=3
            )
            connection = database.get_db()
            assert (await (await connection.execute("SELECT 1")).fetchone())[0] == 1
            with pytest.raises(RuntimeError, match="Database is in use"):
                with backups.database_lock(db_path):
                    pytest.fail("Another process acquired the running app's lock")
            if context_fails:
                raise RuntimeError("request context failed")

    try:
        if context_fails:
            with pytest.raises(RuntimeError, match="request context failed"):
                await exercise_lifespan()
        else:
            await exercise_lifespan()
        assert all(event.is_set() for event in stopped.values())
        assert all(task.done() for task in running)
        client.close.assert_awaited_once()
        assert database._db is None
        with pytest.raises(ValueError, match="no active connection"):
            await connection.execute("SELECT 1")
        with backups.database_lock(db_path):
            pass
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await database.close_db()


async def test_interrupted_restore_blocks_start_before_database_writes(
    tmp_path, monkeypatch
):
    path = tmp_path / "empulse.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE existing_data (value TEXT)")
        conn.execute("INSERT INTO existing_data VALUES ('keep this')")
    original = path.read_bytes()
    marker = tmp_path / ".empulse.db.restore-in-progress"
    marker.write_text("restore requires manual recovery")
    monkeypatch.setattr(database.settings, "db_path", str(path))
    monkeypatch.setattr(database, "_db", None)
    with pytest.raises(RuntimeError, match="Interrupted restore requires recovery"):
        await database.init_db()
    assert path.read_bytes() == original
    assert not (tmp_path / "backups").exists()
    assert database._db is None


async def test_cancelled_backup_worker_keeps_lock_until_thread_finishes(tmp_path):
    path = tmp_path / "empulse.db"
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def blocked_io():
        entered.set()
        try:
            if not release.wait(timeout=5):
                raise TimeoutError("Test did not release backup worker")
        finally:
            completed.set()

    async def perform_backup():
        with backups.database_lock(path):
            await backups.run_io(blocked_io)

    task = asyncio.create_task(perform_backup())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        # Give the cancellation handler a turn before trying the lock.
        await asyncio.sleep(0)
        assert not task.done()
        assert not completed.is_set()
        with pytest.raises(RuntimeError, match="Database is in use"):
            with backups.database_lock(path):
                pytest.fail("Cancelled worker released its lock before finishing")
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()
        with backups.database_lock(path):
            pass
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
