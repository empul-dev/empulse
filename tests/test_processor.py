import pytest
import pytest_asyncio

from emtulli.activity.processor import ActivityProcessor
from emtulli.activity.session_state import SessionStateTracker
from emtulli.emby.models import EmbySessionInfo
from emtulli.db import history as history_db


class TestActivityProcessor:
    @pytest_asyncio.fixture
    async def processor(self, db):
        tracker = SessionStateTracker()
        proc = ActivityProcessor(tracker, lambda: db)
        return proc, tracker

    def _make_session(self, data: dict) -> EmbySessionInfo:
        return EmbySessionInfo(**data)

    @pytest.mark.asyncio
    async def test_new_session_tracked(self, processor, sample_emby_session_data):
        proc, tracker = processor
        session = self._make_session(sample_emby_session_data)

        await proc.process_sessions([session])
        assert len(tracker.get_all_sessions()) == 1

    @pytest.mark.asyncio
    async def test_stopped_session_writes_history(self, processor, db, sample_emby_session_data):
        proc, tracker = processor
        session = self._make_session(sample_emby_session_data)

        # First poll: session active
        await proc.process_sessions([session])
        assert len(tracker.get_all_sessions()) == 1

        # Second poll: session gone
        await proc.process_sessions([])
        assert len(tracker.get_all_sessions()) == 0

        # History should have one record
        rows = await history_db.get_history(db)
        assert len(rows) == 1
        assert rows[0]["user_name"] == "TestUser"
        assert rows[0]["item_name"] == "Test Movie"

    @pytest.mark.asyncio
    async def test_idle_sessions_ignored(self, processor):
        proc, tracker = processor
        idle = self._make_session({
            "Id": "idle1", "UserName": "IdleUser",
            "Client": "Web", "DeviceName": "Chrome",
        })

        await proc.process_sessions([idle])
        assert len(tracker.get_all_sessions()) == 0

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, processor, sample_emby_session_data, sample_emby_episode_data):
        proc, tracker = processor
        s1 = self._make_session(sample_emby_session_data)
        s2 = self._make_session(sample_emby_episode_data)

        await proc.process_sessions([s1, s2])
        assert len(tracker.get_all_sessions()) == 2

    @pytest.mark.asyncio
    async def test_transcode_detection(self, processor, sample_emby_episode_data):
        proc, tracker = processor
        session = self._make_session(sample_emby_episode_data)

        await proc.process_sessions([session])
        sessions = tracker.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["play_method"] == "Transcode"
        assert sessions[0]["transcode_video_codec"] == "h264"

    @pytest.mark.asyncio
    async def test_history_watched_flag(self, processor, db, sample_emby_session_data):
        proc, tracker = processor
        # Set progress to 90% of runtime
        sample_emby_session_data["PlayState"]["PositionTicks"] = 64800000000  # 90% of 72B
        session = self._make_session(sample_emby_session_data)

        await proc.process_sessions([session])
        await proc.process_sessions([])

        rows = await history_db.get_history(db)
        assert len(rows) == 1
        assert rows[0]["watched"] == 1
        assert rows[0]["percent_complete"] == 90.0
