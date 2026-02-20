from empulse.models import SessionInfo, HistoryRecord, UserInfo


class TestSessionInfo:
    def test_progress_percent(self):
        s = SessionInfo(session_key="k1", runtime_ticks=100_000, progress_ticks=50_000)
        assert s.progress_percent == 50.0

    def test_progress_percent_zero_runtime(self):
        s = SessionInfo(session_key="k1", runtime_ticks=0, progress_ticks=0)
        assert s.progress_percent == 0.0

    def test_runtime_minutes(self):
        # 1 hour = 36_000_000_000 ticks
        s = SessionInfo(session_key="k1", runtime_ticks=36_000_000_000)
        assert s.runtime_minutes == 60

    def test_display_title_movie(self):
        s = SessionInfo(session_key="k1", item_name="Inception", year=2010)
        assert s.display_title == "Inception (2010)"

    def test_display_title_episode(self):
        s = SessionInfo(
            session_key="k1", item_name="Pilot",
            series_name="Breaking Bad", season_number=1, episode_number=1,
        )
        assert s.display_title == "Breaking Bad - S01E01 - Pilot"

    def test_display_title_unknown(self):
        s = SessionInfo(session_key="k1")
        assert s.display_title == "Unknown"


class TestHistoryRecord:
    def test_duration_display_hours(self):
        r = HistoryRecord(
            id=1, session_key="k", started_at="2024-01-01", stopped_at="2024-01-01",
            duration_seconds=3661,
        )
        assert r.duration_display == "1h 1m"

    def test_duration_display_minutes(self):
        r = HistoryRecord(
            id=1, session_key="k", started_at="2024-01-01", stopped_at="2024-01-01",
            duration_seconds=125,
        )
        assert r.duration_display == "2m 5s"

    def test_display_title_episode(self):
        r = HistoryRecord(
            id=1, session_key="k", started_at="2024-01-01", stopped_at="2024-01-01",
            item_name="The One Where...", series_name="Friends",
            season_number=3, episode_number=7,
        )
        assert r.display_title == "Friends - S03E07 - The One Where..."


class TestUserInfo:
    def test_total_duration_display_days(self):
        u = UserInfo(emby_user_id="u1", total_duration=100_000)
        assert u.total_duration_display == "1d 3h"

    def test_total_duration_display_hours(self):
        u = UserInfo(emby_user_id="u1", total_duration=7200)
        assert u.total_duration_display == "2h 0m"
