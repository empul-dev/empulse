import httpx

EVENT_LABELS = {
    "playback_start": "▶️ Playback Started",
    "playback_stop": "⏹ Playback Stopped",
    "playback_pause": "⏸ Playback Paused",
    "playback_resume": "▶️ Playback Resumed",
    "watched": "✅ Watched",
    "transcode": "🔄 Transcode Detected",
}


def _build_message(event_type: str, data: dict) -> str:
    label = EVENT_LABELS.get(event_type, event_type)
    title = data.get("item_name", "Unknown")
    series = data.get("series_name")
    if series:
        title = f"{series} \\- {title}"

    user = data.get("user_name", "Unknown")

    lines = [
        f"*{label}*",
        "",
        f"👤 *User:* {_escape(user)}",
        f"🎬 *Title:* {_escape(title)}",
    ]

    if data.get("play_method"):
        lines.append(f"📡 *Play Method:* {_escape(data['play_method'])}")
    if data.get("client"):
        platform = f"{data['client']} ({data.get('device_name', '')})"
        lines.append(f"📱 *Platform:* {_escape(platform)}")
    if data.get("duration_seconds"):
        m, s = divmod(data["duration_seconds"], 60)
        h, m = divmod(m, 60)
        dur = f"{h}h {m}m" if h else f"{m}m {s}s"
        lines.append(f"⏱ *Duration:* {dur}")
    if data.get("percent_complete"):
        lines.append(f"📊 *Progress:* {data['percent_complete']:.0f}%")

    return "\n".join(lines)


def _escape(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    special = r"_*[]()~`>#+-=|{}.!"
    result = ""
    for ch in str(text):
        if ch in special:
            result += f"\\{ch}"
        else:
            result += ch
    return result


async def send_telegram(config: dict, event_type: str, data: dict):
    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")

    if not bot_token or not chat_id:
        raise ValueError("Telegram bot_token and chat_id are required")

    text = _build_message(event_type, data)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        })
        r.raise_for_status()
