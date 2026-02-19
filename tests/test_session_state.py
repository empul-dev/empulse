from emtulli.activity.session_state import SessionStateTracker


class TestSessionStateTracker:
    def test_new_session(self):
        tracker = SessionStateTracker()
        transition = tracker.update_session("s1", {
            "user_name": "Alice", "item_name": "Movie", "is_paused": False,
        })
        assert transition == "new"
        assert len(tracker.get_all_sessions()) == 1

    def test_update_session(self):
        tracker = SessionStateTracker()
        tracker.update_session("s1", {
            "user_name": "Alice", "item_name": "Movie", "is_paused": False,
        })
        transition = tracker.update_session("s1", {
            "user_name": "Alice", "item_name": "Movie", "is_paused": False,
            "progress_ticks": 1000,
        })
        assert transition == "updated"

    def test_pause_resume(self):
        tracker = SessionStateTracker()
        tracker.update_session("s1", {
            "user_name": "Alice", "item_name": "Movie", "is_paused": False,
        })

        transition = tracker.update_session("s1", {
            "user_name": "Alice", "item_name": "Movie", "is_paused": True,
        })
        assert transition == "paused"

        transition = tracker.update_session("s1", {
            "user_name": "Alice", "item_name": "Movie", "is_paused": False,
        })
        assert transition == "resumed"

    def test_remove_session(self):
        tracker = SessionStateTracker()
        tracker.update_session("s1", {
            "user_name": "Alice", "item_name": "Movie", "is_paused": False,
        })

        removed = tracker.remove_session("s1")
        assert removed is not None
        assert removed["user_name"] == "Alice"
        assert len(tracker.get_all_sessions()) == 0

    def test_remove_nonexistent(self):
        tracker = SessionStateTracker()
        assert tracker.remove_session("nope") is None

    def test_get_active_keys(self):
        tracker = SessionStateTracker()
        tracker.update_session("s1", {"is_paused": False})
        tracker.update_session("s2", {"is_paused": False})

        keys = tracker.get_active_keys()
        assert keys == {"s1", "s2"}

    def test_clear(self):
        tracker = SessionStateTracker()
        tracker.update_session("s1", {"is_paused": False})
        tracker.update_session("s2", {"is_paused": False})

        tracker.clear()
        assert len(tracker.get_all_sessions()) == 0

    def test_paused_seconds_accumulated_on_remove(self):
        tracker = SessionStateTracker()
        tracker.update_session("s1", {"is_paused": False})
        # Simulate pause
        tracker.update_session("s1", {"is_paused": True})
        # Remove while paused - should finalize pause time
        removed = tracker.remove_session("s1")
        assert removed is not None
        assert "paused_seconds" in removed
