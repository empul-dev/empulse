import json
import logging
from datetime import datetime, timezone
from typing import Callable

from empulse.activity.session_state import SessionStateTracker
from empulse.emby.models import EmbySessionInfo
from empulse.db import history as history_db, users as users_db

logger = logging.getLogger("empulse.processor")


class ActivityProcessor:
    def __init__(self, state_tracker: SessionStateTracker, db_factory: Callable):
        self.state = state_tracker
        self.get_db = db_factory
        self.notification_engine = None
        self._pending_updates: list[str] = []

    def _build_stream_info(self, s: EmbySessionInfo) -> str:
        """Build a JSON string with source and transcode stream details."""
        item = s.now_playing_item
        tc = s.transcoding_info
        info = {}

        if item:
            # Source video stream
            for ms in item.media_streams:
                if ms.type == "Video" and "video" not in info:
                    framerate = ms.real_frame_rate or ms.average_frame_rate
                    info["video"] = {
                        "codec": (ms.codec or "").upper(),
                        "profile": ms.profile,
                        "bitrate": ms.bit_rate,
                        "width": ms.width,
                        "height": ms.height,
                        "framerate": round(framerate, 1) if framerate else None,
                        "bit_depth": ms.bit_depth,
                        "video_range": ms.video_range or "SDR",
                        "aspect_ratio": ms.aspect_ratio,
                    }
                elif ms.type == "Audio" and "audio" not in info:
                    info["audio"] = {
                        "codec": (ms.codec or "").upper(),
                        "bitrate": ms.bit_rate,
                        "channels": ms.channels,
                        "sample_rate": ms.sample_rate,
                        "language": ms.language,
                    }

            # Media container
            if item.container:
                total_bitrate = None
                vid = info.get("video", {})
                aud = info.get("audio", {})
                if vid.get("bitrate") or aud.get("bitrate"):
                    total_bitrate = (vid.get("bitrate") or 0) + (aud.get("bitrate") or 0)
                info["media"] = {
                    "container": (item.container or "").upper(),
                    "bitrate": total_bitrate,
                    "resolution": f"{vid.get('height', '')}p" if vid.get("height") else None,
                }

        # Transcode output details
        if tc:
            info["transcode"] = {
                "video_codec": (tc.video_codec or "").upper() if tc.video_codec else None,
                "audio_codec": (tc.audio_codec or "").upper() if tc.audio_codec else None,
                "container": (tc.container or "").upper() if tc.container else None,
                "bitrate": tc.bitrate,
                "video_bitrate": tc.video_bitrate,
                "audio_bitrate": tc.audio_bitrate,
                "width": tc.width,
                "height": tc.height,
                "framerate": tc.framerate,
                "audio_channels": tc.audio_channels,
                "is_video_direct": tc.is_video_direct,
                "is_audio_direct": tc.is_audio_direct,
            }

        return json.dumps(info) if info else "{}"

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
            "series_id": item.series_id if item else None,
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
            "stream_info": self._build_stream_info(s),
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

        # Stopped sessions — finalize their history records
        stopped = current_keys - new_keys
        for key in stopped:
            session = self.state.remove_session(key)
            if session:
                await self._finalize_history(session)
                await self._emit("playback_stop", session)

        # New or updated sessions
        for key, emby_session in active.items():
            data = self._build_session_data(emby_session)
            transition = self.state.update_session(key, data)
            if transition == "new":
                await self._start_history(key, data)
                await self._emit("playback_start", data)
                if data.get("play_method") == "Transcode":
                    await self._emit("transcode", data)
            elif transition == "paused":
                await self._emit("playback_pause", data)
            elif transition == "resumed":
                await self._emit("playback_resume", data)

            # Queue in-progress history updates (state changes flush immediately)
            if transition in ("updated", "paused", "resumed"):
                self._queue_history_update(key, force=transition != "updated")

        # Flush all queued updates in a single transaction
        await self._flush_history_updates()

    async def _emit(self, event_type: str, data: dict):
        if self.notification_engine:
            try:
                await self.notification_engine.emit(event_type, data)
            except Exception as e:
                logger.error(f"Notification emit error: {e}")

    def _calc_progress(self, session: dict) -> dict:
        """Calculate duration/progress stats from a session dict.

        Accounts for base_duration/base_paused from merged records so the DB
        total accumulates correctly across resumed sessions.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        started = session.get("started_at", now_iso)
        paused_seconds = session.get("paused_seconds", 0)

        try:
            start_dt = datetime.fromisoformat(started)
        except (ValueError, TypeError):
            start_dt = now

        wall_duration = int((now - start_dt).total_seconds())
        wall_actual = max(0, wall_duration - paused_seconds)

        # Prefer tick-based duration from the player's reported position.
        # Wall-clock is unreliable when sessions appear/disappear from the API.
        start_ticks = session.get("start_progress_ticks", 0)
        end_ticks = session.get("progress_ticks", 0)
        tick_duration = max(0, (end_ticks - start_ticks) // 10_000_000)

        # Use whichever is larger — tick-based catches late detection,
        # wall-clock catches re-watches of the same segment.
        session_duration = max(tick_duration, wall_actual)

        # Add base values from a prior merged record
        base_duration = session.get("base_duration", 0)
        base_paused = session.get("base_paused", 0)
        total_duration = base_duration + session_duration
        total_paused = base_paused + paused_seconds

        runtime = session.get("runtime_ticks", 0)
        progress = session.get("progress_ticks", 0)
        percent = round(progress / runtime * 100, 1) if runtime else 0
        watched = percent >= 80

        return {
            "stopped_at": now_iso,
            "duration_seconds": total_duration,
            "paused_seconds": total_paused,
            "pause_events": json.dumps(session.get("pause_events", [])),
            "percent_complete": percent,
            "watched": 1 if watched else 0,
            "progress_ticks": progress,
            "stream_info": session.get("stream_info", "{}"),
            "_session_duration": session_duration,  # just this session's portion
        }

    async def _start_history(self, session_key: str, session: dict):
        """Create a history record when playback starts (or merge into a recent one)."""
        db = self.get_db()
        user_id = session.get("user_id")
        item_id = session.get("item_id")
        stats = self._calc_progress(session)

        # Check if we should merge into a recent record for same user+item
        existing = None
        if user_id and item_id:
            existing = await history_db.find_recent_history(db, user_id, item_id)

        if existing:
            history_id = existing["id"]
            base_duration = existing.get("duration_seconds", 0)
            base_paused = existing.get("paused_seconds", 0)
            # Load existing pause events so they're not lost on merge
            base_pause_events = []
            try:
                raw = existing.get("pause_events", "[]")
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list):
                    base_pause_events = parsed
            except (ValueError, TypeError):
                pass
            # Store base values so future updates accumulate correctly.
            # Don't update DB here — the next poll cycle will do it with correct totals.
            self.state.set_history_id(session_key, history_id, base_duration, base_paused, base_pause_events)
            logger.info(
                f"History resumed (id={history_id}): {session.get('user_name')} - "
                f"{session.get('item_name')}"
            )
            return
        else:
            record = {
                "session_key": session.get("session_key", ""),
                "user_id": user_id,
                "user_name": session.get("user_name"),
                "client": session.get("client"),
                "device_name": session.get("device_name"),
                "ip_address": session.get("ip_address"),
                "item_id": item_id,
                "item_name": session.get("item_name"),
                "item_type": session.get("item_type"),
                "series_name": session.get("series_name"),
                "series_id": session.get("series_id"),
                "season_number": session.get("season_number"),
                "episode_number": session.get("episode_number"),
                "year": session.get("year"),
                "runtime_ticks": session.get("runtime_ticks", 0),
                "progress_ticks": stats["progress_ticks"],
                "play_method": session.get("play_method"),
                "transcode_video_codec": session.get("transcode_video_codec"),
                "transcode_audio_codec": session.get("transcode_audio_codec"),
                "video_decision": session.get("video_decision"),
                "audio_decision": session.get("audio_decision"),
                "stream_info": stats["stream_info"],
                "started_at": session.get("started_at"),
                "stopped_at": stats["stopped_at"],
                "duration_seconds": stats["duration_seconds"],
                "paused_seconds": stats["paused_seconds"],
                "percent_complete": stats["percent_complete"],
                "watched": stats["watched"],
            }
            history_id = await history_db.insert_history_returning_id(db, record)
            logger.info(
                f"History started (id={history_id}): {session.get('user_name')} - "
                f"{session.get('item_name')}"
            )

        self.state.set_history_id(session_key, history_id)
        # Mark the initial write so throttling starts from here
        if session_key in self.state._sessions:
            self.state._sessions[session_key]["last_db_write"] = datetime.now(timezone.utc).isoformat()

    # How often (seconds) to write routine progress updates per session.
    # State changes (pause/resume/stop) always write immediately.
    DB_WRITE_INTERVAL = 30

    def _queue_history_update(self, session_key: str, force: bool = False):
        """Add a session to the pending-update queue if enough time has elapsed."""
        session = self.state._sessions.get(session_key)
        if not session or not session.get("history_id"):
            return

        if not force:
            last_write = session.get("last_db_write")
            if last_write:
                try:
                    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_write)).total_seconds()
                    if elapsed < self.DB_WRITE_INTERVAL:
                        return
                except (ValueError, TypeError):
                    pass

        self._pending_updates.append(session_key)

    async def _flush_history_updates(self):
        """Batch-write all queued history updates in a single transaction."""
        pending = getattr(self, "_pending_updates", [])
        if not pending:
            return
        self._pending_updates = []

        db = self.get_db()
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            for session_key in pending:
                session = self.state._sessions.get(session_key)
                if not session:
                    continue
                history_id = session.get("history_id")
                if not history_id:
                    continue
                stats = self._calc_progress(session)
                await db.execute(
                    "UPDATE history SET stopped_at = ?, duration_seconds = ?, paused_seconds = ?, "
                    "pause_events = ?, percent_complete = ?, watched = ?, progress_ticks = ?, stream_info = ? WHERE id = ?",
                    [
                        stats["stopped_at"],
                        stats["duration_seconds"],
                        stats["paused_seconds"],
                        stats.get("pause_events", "[]"),
                        stats["percent_complete"],
                        stats["watched"],
                        stats.get("progress_ticks", 0),
                        stats.get("stream_info", "{}"),
                        history_id,
                    ],
                )
                session["last_db_write"] = now_iso
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to flush {len(pending)} history updates: {e}")

    async def _finalize_history(self, session: dict):
        """Finalize a history record when playback stops and update user stats."""
        history_id = session.get("history_id")
        stats = self._calc_progress(session)
        db = self.get_db()
        user_id = session.get("user_id")

        if history_id:
            # Update the existing record with final values
            try:
                await history_db.update_active_history(db, history_id, stats)
            except Exception as e:
                logger.error(f"Failed to finalize history {history_id}: {e}")

            # Update user stats with only this session's duration (not the merged total)
            if user_id:
                await users_db.update_user_stats(db, user_id, stats["_session_duration"])

            if stats["watched"]:
                await self._emit("watched", session)

            logger.info(
                f"History finalized (id={history_id}): {session.get('user_name')} - "
                f"{session.get('item_name')} ({stats['duration_seconds']}s, {stats['percent_complete']}%)"
            )
        else:
            # Fallback: no history_id (shouldn't happen normally, but handle gracefully)
            logger.warning(
                f"No history_id for stopped session: {session.get('user_name')} - "
                f"{session.get('item_name')}, writing new record"
            )
            record = {
                "session_key": session.get("session_key", ""),
                "user_id": user_id,
                "user_name": session.get("user_name"),
                "client": session.get("client"),
                "device_name": session.get("device_name"),
                "ip_address": session.get("ip_address"),
                "item_id": session.get("item_id"),
                "item_name": session.get("item_name"),
                "item_type": session.get("item_type"),
                "series_name": session.get("series_name"),
                "series_id": session.get("series_id"),
                "season_number": session.get("season_number"),
                "episode_number": session.get("episode_number"),
                "year": session.get("year"),
                "runtime_ticks": session.get("runtime_ticks", 0),
                "progress_ticks": stats["progress_ticks"],
                "play_method": session.get("play_method"),
                "transcode_video_codec": session.get("transcode_video_codec"),
                "transcode_audio_codec": session.get("transcode_audio_codec"),
                "video_decision": session.get("video_decision"),
                "audio_decision": session.get("audio_decision"),
                "stream_info": stats["stream_info"],
                "started_at": session.get("started_at"),
                "stopped_at": stats["stopped_at"],
                "duration_seconds": stats["duration_seconds"],
                "paused_seconds": stats["paused_seconds"],
                "percent_complete": stats["percent_complete"],
                "watched": stats["watched"],
            }
            await history_db.insert_history(db, record)

            if user_id:
                await users_db.update_user_stats(db, user_id, stats["duration_seconds"])

            if stats["watched"]:
                await self._emit("watched", session)
