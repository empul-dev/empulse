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
        paused_seconds = session.get("paused_seconds", 0)

        try:
            start_dt = datetime.fromisoformat(started)
        except (ValueError, TypeError):
            start_dt = datetime.now(timezone.utc)

        stop_dt = datetime.now(timezone.utc)
        duration = int((stop_dt - start_dt).total_seconds())
        actual_duration = max(0, duration - paused_seconds)

        runtime = session.get("runtime_ticks", 0)
        progress = session.get("progress_ticks", 0)
        percent = round(progress / runtime * 100, 1) if runtime else 0
        watched = percent >= 80

        db = self.get_db()
        user_id = session.get("user_id")
        item_id = session.get("item_id")

        # Try to merge with a recent history record for the same user+item
        existing = None
        if user_id and item_id:
            existing = await history_db.find_recent_history(db, user_id, item_id)

        if existing:
            # Merge: keep original start time, accumulate duration and pause
            merged_duration = existing["duration_seconds"] + actual_duration
            merged_paused = existing.get("paused_seconds", 0) + paused_seconds
            # Use the higher progress/percent
            merged_percent = max(existing.get("percent_complete", 0), percent)
            merged_watched = 1 if merged_percent >= 80 else 0
            merged_progress = max(existing.get("progress_ticks", 0), progress)

            await history_db.merge_history(db, existing["id"], {
                "stopped_at": now,
                "duration_seconds": merged_duration,
                "paused_seconds": merged_paused,
                "percent_complete": merged_percent,
                "watched": merged_watched,
                "progress_ticks": merged_progress,
                "stream_info": session.get("stream_info", "{}"),
            })

            # Update user stats only for the new portion
            if user_id:
                await users_db.update_user_stats(db, user_id, actual_duration)

            logger.info(
                f"History merged (id={existing['id']}): {session.get('user_name')} - "
                f"{session.get('item_name')} (+{actual_duration}s, {merged_percent}%)"
            )
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
                "runtime_ticks": runtime,
                "progress_ticks": progress,
                "play_method": session.get("play_method"),
                "transcode_video_codec": session.get("transcode_video_codec"),
                "transcode_audio_codec": session.get("transcode_audio_codec"),
                "video_decision": session.get("video_decision"),
                "audio_decision": session.get("audio_decision"),
                "stream_info": session.get("stream_info", "{}"),
                "started_at": started,
                "stopped_at": now,
                "duration_seconds": actual_duration,
                "paused_seconds": paused_seconds,
                "percent_complete": percent,
                "watched": 1 if watched else 0,
            }

            await history_db.insert_history(db, record)

            if user_id:
                await users_db.update_user_stats(db, user_id, actual_duration)

            logger.info(
                f"History written: {session.get('user_name')} - {session.get('item_name')} "
                f"({actual_duration}s, {percent}%)"
            )
