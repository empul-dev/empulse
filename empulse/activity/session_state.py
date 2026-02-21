import logging
from datetime import datetime, timezone

logger = logging.getLogger("empulse.state")


class SessionStateTracker:
    """In-memory tracker for active playback sessions."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def update_session(self, session_key: str, data: dict) -> str:
        """Update or create a session. Returns the transition: 'new', 'updated', 'paused', 'resumed', or 'unchanged'."""
        now = datetime.now(timezone.utc).isoformat()

        if session_key not in self._sessions:
            data["started_at"] = now
            data["updated_at"] = now
            data["paused_seconds"] = 0
            # If the session is already paused when first seen, start tracking the pause
            if data.get("is_paused"):
                data["pause_start"] = now
            else:
                data["pause_start"] = None
            self._sessions[session_key] = data
            logger.info(f"New session: {session_key} - {data.get('user_name')} playing {data.get('item_name')}")
            return "new"

        existing = self._sessions[session_key]
        was_paused = existing.get("is_paused", False)
        is_paused = data.get("is_paused", False)

        # Track pause duration
        if is_paused and not was_paused:
            data["pause_start"] = now
            data["paused_seconds"] = existing.get("paused_seconds", 0)
            transition = "paused"
        elif not is_paused and was_paused and existing.get("pause_start"):
            pause_start = datetime.fromisoformat(existing["pause_start"])
            pause_dur = (datetime.now(timezone.utc) - pause_start).total_seconds()
            data["paused_seconds"] = existing.get("paused_seconds", 0) + int(pause_dur)
            data["pause_start"] = None
            transition = "resumed"
        else:
            data["paused_seconds"] = existing.get("paused_seconds", 0)
            data["pause_start"] = existing.get("pause_start")
            transition = "updated"

        data["started_at"] = existing["started_at"]
        data["updated_at"] = now
        self._sessions[session_key] = data
        return transition

    def remove_session(self, session_key: str) -> dict | None:
        """Remove and return a session (playback stopped)."""
        session = self._sessions.pop(session_key, None)
        if session:
            # Finalize any ongoing pause
            if session.get("pause_start"):
                pause_start = datetime.fromisoformat(session["pause_start"])
                pause_dur = (datetime.now(timezone.utc) - pause_start).total_seconds()
                session["paused_seconds"] = session.get("paused_seconds", 0) + int(pause_dur)
            logger.info(f"Session ended: {session_key} - {session.get('user_name')}")
        return session

    def get_all_sessions(self) -> list[dict]:
        return list(self._sessions.values())

    def get_active_keys(self) -> set[str]:
        return set(self._sessions.keys())

    def clear(self):
        self._sessions.clear()
