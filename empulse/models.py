from datetime import datetime

from pydantic import BaseModel


class SessionInfo(BaseModel):
    session_key: str
    emby_session_id: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    client: str | None = None
    device_name: str | None = None
    ip_address: str | None = None
    item_id: str | None = None
    item_name: str | None = None
    item_type: str | None = None
    series_name: str | None = None
    series_id: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    year: int | None = None
    runtime_ticks: int = 0
    progress_ticks: int = 0
    is_paused: bool = False
    play_method: str | None = None
    transcode_video_codec: str | None = None
    transcode_audio_codec: str | None = None
    video_decision: str | None = None
    audio_decision: str | None = None
    state: str = "playing"

    @property
    def poster_id(self) -> str | None:
        """Use series poster for episodes, item poster for movies."""
        if self.item_type == "Episode" and self.series_id:
            return self.series_id
        return self.item_id

    @property
    def progress_percent(self) -> float:
        if self.runtime_ticks and self.runtime_ticks > 0:
            return round(self.progress_ticks / self.runtime_ticks * 100, 1)
        return 0.0

    @property
    def runtime_minutes(self) -> int:
        return int(self.runtime_ticks / 600_000_000) if self.runtime_ticks else 0

    @property
    def progress_minutes(self) -> int:
        return int(self.progress_ticks / 600_000_000) if self.progress_ticks else 0

    @property
    def display_title(self) -> str:
        if (
            self.series_name
            and self.season_number is not None
            and self.episode_number is not None
        ):
            return f"{self.series_name} - S{self.season_number:02d}E{self.episode_number:02d} - {self.item_name}"
        if self.item_name and self.year:
            return f"{self.item_name} ({self.year})"
        return self.item_name or "Unknown"


class HistoryRecord(BaseModel):
    id: int
    session_key: str
    user_id: str | None = None
    user_name: str | None = None
    client: str | None = None
    device_name: str | None = None
    ip_address: str | None = None
    item_id: str | None = None
    item_name: str | None = None
    item_type: str | None = None
    series_name: str | None = None
    series_id: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    year: int | None = None
    runtime_ticks: int = 0
    progress_ticks: int = 0
    play_method: str | None = None
    video_decision: str | None = None
    audio_decision: str | None = None
    transcode_video_codec: str | None = None
    transcode_audio_codec: str | None = None
    stream_info: str = "{}"
    started_at: str = ""
    stopped_at: str = ""
    duration_seconds: int = 0
    paused_seconds: int = 0
    pause_events: str = "[]"
    percent_complete: float = 0
    watched: bool = False

    @property
    def poster_id(self) -> str | None:
        if self.item_type == "Episode" and self.series_id:
            return self.series_id
        return self.item_id

    @property
    def item_link(self) -> str:
        """Link to item detail page (episode-level for episodes)."""
        if self.item_id:
            return f"/item/{self.item_id}"
        return "#"

    @property
    def display_title(self) -> str:
        if (
            self.series_name
            and self.season_number is not None
            and self.episode_number is not None
        ):
            return f"{self.series_name} - S{self.season_number:02d}E{self.episode_number:02d} - {self.item_name}"
        if self.item_name and self.year:
            return f"{self.item_name} ({self.year})"
        return self.item_name or "Unknown"

    @property
    def title_short(self) -> str:
        """Shorter title for table display."""
        if (
            self.series_name
            and self.season_number is not None
            and self.episode_number is not None
        ):
            return f"{self.series_name} (S{self.season_number:02d} · E{self.episode_number:02d})"
        if self.item_name and self.year:
            return f"{self.item_name} ({self.year})"
        return self.item_name or "Unknown"

    @property
    def type_icon(self) -> str:
        icons = {"Movie": "film", "Episode": "tv", "Audio": "music"}
        return icons.get(self.item_type or "", "")

    @property
    def platform_name(self) -> str:
        """Derive platform/OS from client and device_name."""
        c = (self.client or "").lower()
        d = (self.device_name or "").lower()
        if "ios" in c or "iphone" in d or "ipad" in d:
            return "iOS"
        if "android" in c or "android" in d:
            return "Android"
        if "apple tv" in d or "tvos" in c:
            return "tvOS"
        if "fire" in d or "amazon" in d:
            return "Fire TV"
        if "roku" in d or "roku" in c:
            return "Roku"
        if "samsung" in d or "tizen" in c:
            return "Tizen"
        if "lg" in d or "webos" in c:
            return "webOS"
        if "chrome" in d or "firefox" in d or "safari" in d or "edge" in d:
            return d.split()[0].title() if d else "Browser"
        if "web" in c:
            return "Web"
        if "theater" in c or "windows" in c or "desktop" in c:
            return "Windows"
        if "mac" in d:
            return "macOS"
        if "linux" in d:
            return "Linux"
        return self.client or ""

    @property
    def started_time(self) -> str:
        return self.started_at[11:16] if len(self.started_at) > 16 else ""

    @property
    def stopped_time(self) -> str:
        return self.stopped_at[11:16] if len(self.stopped_at) > 16 else ""

    @property
    def started_date(self) -> str:
        return self.started_at[:10] if len(self.started_at) >= 10 else ""

    @property
    def paused_display(self) -> str:
        if not self.paused_seconds:
            return "0 mins"
        m = self.paused_seconds // 60
        return f"{m} mins"

    @property
    def duration_mins(self) -> str:
        m = self.duration_seconds // 60
        return f"{m} mins"

    @property
    def duration_display(self) -> str:
        """How much content was watched (from progress_ticks position)."""
        if self.progress_ticks:
            total = int(self.progress_ticks / 10_000_000)
        else:
            total = self.duration_seconds
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m"
        return f"{m}m {s}s"

    @property
    def session_time_display(self) -> str:
        """Total wall-clock session time from started_at to stopped_at."""
        try:
            start = datetime.fromisoformat(self.started_at)
            stop = datetime.fromisoformat(self.stopped_at)
            total = max(0, int((stop - start).total_seconds()))
        except (ValueError, TypeError):
            total = self.duration_seconds
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m"
        return f"{m}m {s}s"

    @property
    def runtime_display(self) -> str:
        if not self.runtime_ticks:
            return ""
        total = int(self.runtime_ticks / 10_000_000)
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m"
        return f"{m}m {s}s"

    @property
    def progress_display(self) -> str:
        if not self.progress_ticks:
            return ""
        total = int(self.progress_ticks / 10_000_000)
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m {s}s"
        return f"{m}m {s}s"

    @property
    def started_at_full(self) -> str:
        if len(self.started_at) >= 19:
            return self.started_at[:10] + " " + self.started_at[11:19]
        return self.started_at

    @property
    def stopped_at_full(self) -> str:
        if len(self.stopped_at) >= 19:
            return self.stopped_at[:10] + " " + self.stopped_at[11:19]
        return self.stopped_at

    @property
    def parsed_pause_events(self) -> list[dict]:
        import json as _json

        try:
            events = _json.loads(self.pause_events) if self.pause_events else []
            return events if isinstance(events, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def pause_markers(self) -> list[dict]:
        """Build pause markers positioned on the content timeline (0-100% of runtime).

        Each marker has {pct, label} where pct is the position within the
        content based on position_ticks at the time of the pause.
        """
        runtime = self.runtime_ticks
        if not runtime:
            return []

        markers = []
        for ev in self.parsed_pause_events:
            ticks = ev.get("position_ticks", 0)
            pct = round(ticks / runtime * 100, 1)
            dur_s = ev.get("duration_s", 0)
            m, s = divmod(dur_s, 60)
            dur_label = f"{m}m {s}s" if m else f"{s}s"
            time_str = ""
            start = ev.get("start", "")
            if len(start) >= 19:
                time_str = start[11:19]
            markers.append(
                {
                    "pct": min(pct, 100),
                    "label": f"Paused {dur_label} at {time_str}"
                    if time_str
                    else f"Paused {dur_label}",
                    "start_iso": start,
                }
            )
        return markers


class UserInfo(BaseModel):
    emby_user_id: str
    username: str | None = None
    is_admin: bool = False
    enabled: bool = False
    thumb_url: str | None = None
    last_seen: str | None = None
    total_plays: int = 0
    total_duration: int = 0

    @property
    def total_duration_display(self) -> str:
        m, _ = divmod(self.total_duration, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        if d:
            return f"{d}d {h}h"
        return f"{h}h {m}m"

    @property
    def last_seen_display(self) -> str:
        if not self.last_seen:
            return "Never"
        try:
            dt = datetime.fromisoformat(self.last_seen)
            return dt.strftime("%b %d, %Y %H:%M")
        except (ValueError, TypeError):
            return self.last_seen


class LibraryInfo(BaseModel):
    emby_library_id: str
    name: str | None = None
    library_type: str | None = None
    item_count: int = 0
