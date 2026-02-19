import logging
from datetime import datetime, timezone
from typing import Callable

from emtulli.activity.session_state import SessionStateTracker
from emtulli.emby.models import EmbySessionInfo
from emtulli.db import history as history_db, users as users_db

logger = logging.getLogger("emtulli.processor")


class ActivityProcessor:
    def __init__(self, state_tracker: SessionStateTracker, db_factory: Callable):
        self.state = state_tracker
        self.get_db = db_factory

    def _build_session_data(self, s: EmbySessionInfo) -> dict:
        item = s.now_playing_item
        ps = s.play_state
        tc = s.transcoding_info

        # Determine video/audio decision
        video_decision = "Direct Play"
        audio_decision = "Direct Play"
        if tc:
            if tc.video_codec:
                video_decision = "Transcode"
            if tc.audio_codec:
                audio_decision = "Transcode"

        play_method = ps.play_method if ps else None
        if play_method == "DirectPlay":
            play_method = "DirectPlay"
        elif play_method == "Transcode":
            play_method = "Transcode"
        elif play_method == "DirectStream":
            play_method = "DirectStream"

        return {
            "session_key": f"{s.user_id}_{s.device_id}_{item.id}" if item else s.id,
            "user_id": s.user_id,
            "user_name": s.user_name,
            "client": s.client,
            "device_name": s.device_name,
            "ip_address": s.remote_end_point,
            "item_id": item.id if item else None,
            "item_name": item.name if item else None,
            "item_type": item.type if item else None,
            "series_name": item.series_name if item else None,
            "season_number": item.parent_index_number if item else None,
            "episode_number": item.index_number if item else None,
            "year": item.production_year if item else None,
            "runtime_ticks": item.run_time_ticks or 0 if item else 0,
            "progress_ticks": ps.position_ticks or 0 if ps else 0,
            "is_paused": ps.is_paused if ps else False,
            "play_method": play_method,
            "transcode_video_codec": tc.video_codec if tc else None,
            "transcode_audio_codec": tc.audio_codec if tc else None,
            "video_decision": video_decision,
            "audio_decision": audio_decision,
            "state": "paused" if (ps and ps.is_paused) else "playing",
        }

    async def process_sessions(self, emby_sessions: list[EmbySessionInfo]):
        """Process a fresh list of sessions from Emby. Detect new, updated, and stopped sessions."""
        # Filter to only sessions that are actually playing something
        active = {
            f"{s.user_id}_{s.device_id}_{s.now_playing_item.id}": s
            for s in emby_sessions
            if s.now_playing_item and s.user_id
        }

        current_keys = self.state.get_active_keys()
        new_keys = set(active.keys())

        # Stopped sessions
        stopped = current_keys - new_keys
        for key in stopped:
            session = self.state.remove_session(key)
            if session:
                await self._write_history(session)

        # New or updated sessions
        for key, emby_session in active.items():
            data = self._build_session_data(emby_session)
            self.state.update_session(key, data)

    async def _write_history(self, session: dict):
        now = datetime.now(timezone.utc).isoformat()
        started = session.get("started_at", now)

        try:
            start_dt = datetime.fromisoformat(started)
        except (ValueError, TypeError):
            start_dt = datetime.now(timezone.utc)

        stop_dt = datetime.now(timezone.utc)
        duration = int((stop_dt - start_dt).total_seconds())
        paused_seconds = session.get("paused_seconds", 0)
        actual_duration = max(0, duration - paused_seconds)

        runtime = session.get("runtime_ticks", 0)
        progress = session.get("progress_ticks", 0)
        percent = round(progress / runtime * 100, 1) if runtime else 0
        watched = percent >= 80

        record = {
            "session_key": session.get("session_key", ""),
            "user_id": session.get("user_id"),
            "user_name": session.get("user_name"),
            "client": session.get("client"),
            "device_name": session.get("device_name"),
            "ip_address": session.get("ip_address"),
            "item_id": session.get("item_id"),
            "item_name": session.get("item_name"),
            "item_type": session.get("item_type"),
            "series_name": session.get("series_name"),
            "season_number": session.get("season_number"),
            "episode_number": session.get("episode_number"),
            "year": session.get("year"),
            "runtime_ticks": runtime,
            "progress_ticks": progress,
            "play_method": session.get("play_method"),
            "transcode_video_codec": session.get("transcode_video_codec"),
            "transcode_audio_codec": session.get("transcode_audio_codec"),
            "video_decision": session.get("video_decision"),
            "audio_decision": session.get("audio_decision"),
            "started_at": started,
            "stopped_at": now,
            "duration_seconds": actual_duration,
            "paused_seconds": paused_seconds,
            "percent_complete": percent,
            "watched": 1 if watched else 0,
        }

        db = self.get_db()
        await history_db.insert_history(db, record)

        # Update user stats
        if session.get("user_id"):
            await users_db.update_user_stats(db, session["user_id"], actual_duration)

        logger.info(
            f"History written: {session.get('user_name')} - {session.get('item_name')} "
            f"({actual_duration}s, {percent}%)"
        )
