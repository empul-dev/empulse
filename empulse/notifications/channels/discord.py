import httpx

from empulse.notifications.url_validator import validate_outbound_url

EVENT_COLORS = {
    "playback_start": 0x2ECC71,   # green
    "playback_stop": 0xE74C3C,    # red
    "playback_pause": 0xF39C12,   # yellow
    "playback_resume": 0x3498DB,  # blue
    "watched": 0xF1C40F,          # gold
    "transcode": 0x9B59B6,        # purple
}

EVENT_LABELS = {
    "playback_start": "Playback Started",
    "playback_stop": "Playback Stopped",
    "playback_pause": "Playback Paused",
    "playback_resume": "Playback Resumed",
    "watched": "Watched",
    "transcode": "Transcode Detected",
}


async def send_discord(config: dict, event_type: str, data: dict):
    url = config.get("url", "")
    if not url:
        raise ValueError("Discord webhook URL not configured")

    error = validate_outbound_url(url)
    if error:
        raise ValueError(f"Discord webhook URL blocked: {error}")

    title = data.get("item_name", "Unknown")
    series = data.get("series_name")
    if series:
        title = f"{series} - {title}"

    fields = [
        {"name": "User", "value": data.get("user_name", "Unknown"), "inline": True},
        {"name": "Title", "value": title, "inline": True},
    ]

    if data.get("play_method"):
        fields.append({"name": "Play Method", "value": data["play_method"], "inline": True})
    if data.get("client"):
        fields.append({"name": "Platform", "value": f"{data['client']} ({data.get('device_name', '')})", "inline": True})
    if data.get("duration_seconds"):
        m, s = divmod(data["duration_seconds"], 60)
        h, m = divmod(m, 60)
        dur = f"{h}h {m}m" if h else f"{m}m {s}s"
        fields.append({"name": "Duration", "value": dur, "inline": True})
    if data.get("percent_complete"):
        fields.append({"name": "Progress", "value": f"{data['percent_complete']:.0f}%", "inline": True})

    embed = {
        "title": EVENT_LABELS.get(event_type, event_type),
        "color": EVENT_COLORS.get(event_type, 0x95A5A6),
        "fields": fields,
    }

    # Add poster thumbnail if available
    poster_url = config.get("poster_base_url")
    poster_id = data.get("series_id") if data.get("item_type") == "Episode" else data.get("item_id")
    if poster_url and poster_id:
        embed["thumbnail"] = {"url": f"{poster_url}/api/img/{poster_id}"}

    payload = {"embeds": [embed]}

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
