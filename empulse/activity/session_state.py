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
            data["start_progress_ticks"] = data.get("progress_ticks", 0)
            data["pause_events"] = []
            data["history_id"] = None
            data["last_db_write"] = None
            # If the session is already paused when first seen, start tracking the pause
            if data.get("is_paused"):
                data["pause_start"] = now
                data["pause_start_ticks"] = data.get("progress_ticks", 0)
            else:
                data["pause_start"] = None
                data["pause_start_ticks"] = None
            self._sessions[session_key] = data
            logger.info(f"New session: {session_key} - {data.get('user_name')} playing {data.get('item_name')}")
            return "new"

        existing = self._sessions[session_key]
        was_paused = existing.get("is_paused", False)
        is_paused = data.get("is_paused", False)

        # Carry over pause events list
        data["pause_events"] = list(existing.get("pause_events", []))

        # Track pause duration
        if is_paused and not was_paused:
            data["pause_start"] = now
            data["pause_start_ticks"] = data.get("progress_ticks", 0)
            data["paused_seconds"] = existing.get("paused_seconds", 0)
            transition = "paused"
        elif not is_paused and was_paused and existing.get("pause_start"):
            pause_start = datetime.fromisoformat(existing["pause_start"])
            pause_dur = (datetime.now(timezone.utc) - pause_start).total_seconds()
            data["paused_seconds"] = existing.get("paused_seconds", 0) + int(pause_dur)
            data["pause_start"] = None
            data["pause_start_ticks"] = None
            # Record the completed pause event
            data["pause_events"].append({
                "start": existing["pause_start"],
                "end": now,
                "duration_s": int(pause_dur),
                "position_ticks": existing.get("pause_start_ticks", 0),
            })
            transition = "resumed"
        else:
            data["paused_seconds"] = existing.get("paused_seconds", 0)
            data["pause_start"] = existing.get("pause_start")
            data["pause_start_ticks"] = existing.get("pause_start_ticks")
            transition = "updated"

        data["started_at"] = existing["started_at"]
        data["start_progress_ticks"] = existing.get("start_progress_ticks", 0)
        data["updated_at"] = now
        data["history_id"] = existing.get("history_id")
        data["base_duration"] = existing.get("base_duration", 0)
        data["base_paused"] = existing.get("base_paused", 0)
        data["last_db_write"] = existing.get("last_db_write")
        self._sessions[session_key] = data
        return transition

    def remove_session(self, session_key: str) -> dict | None:
        """Remove and return a session (playback stopped)."""
        session = self._sessions.pop(session_key, None)
        if session:
            # Finalize any ongoing pause
            if session.get("pause_start"):
                now = datetime.now(timezone.utc)
                pause_start = datetime.fromisoformat(session["pause_start"])
                pause_dur = (now - pause_start).total_seconds()
                session["paused_seconds"] = session.get("paused_seconds", 0) + int(pause_dur)
                # Record the final pause event
                events = session.get("pause_events", [])
                events.append({
                    "start": session["pause_start"],
                    "end": now.isoformat(),
                    "duration_s": int(pause_dur),
                    "position_ticks": session.get("pause_start_ticks", 0),
                })
                session["pause_events"] = events
            logger.info(f"Session ended: {session_key} - {session.get('user_name')}")
        return session

    def set_history_id(self, session_key: str, history_id: int, base_duration: int = 0, base_paused: int = 0, base_pause_events: list | None = None):
        """Associate a DB history row with this session.

        base_duration/base_paused: accumulated values from a prior merged record,
        so updates can add the current session's values on top.
        base_pause_events: pause events from the prior record to preserve across merges.
        """
        if session_key in self._sessions:
            self._sessions[session_key]["history_id"] = history_id
            self._sessions[session_key]["base_duration"] = base_duration
            self._sessions[session_key]["base_paused"] = base_paused
            if base_pause_events:
                # Prepend prior events so they're not lost on merge
                existing_events = self._sessions[session_key].get("pause_events", [])
                self._sessions[session_key]["pause_events"] = base_pause_events + existing_events

    def get_all_sessions(self) -> list[dict]:
        return list(self._sessions.values())

    def get_active_keys(self) -> set[str]:
        return set(self._sessions.keys())

    def clear(self):
        self._sessions.clear()
