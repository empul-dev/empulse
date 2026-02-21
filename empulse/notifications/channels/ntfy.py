import httpx

from empulse.notifications.url_validator import validate_outbound_url

EVENT_LABELS = {
    "playback_start": "Playback Started",
    "playback_stop": "Playback Stopped",
    "playback_pause": "Playback Paused",
    "playback_resume": "Playback Resumed",
    "watched": "Watched",
    "transcode": "Transcode Detected",
}

EVENT_TAGS = {
    "playback_start": "arrow_forward",
    "playback_stop": "stop_button",
    "playback_pause": "pause_button",
    "playback_resume": "arrow_forward",
    "watched": "white_check_mark",
    "transcode": "arrows_counterclockwise",
}


async def send_ntfy(config: dict, event_type: str, data: dict):
    server_url = config.get("server_url", "https://ntfy.sh").rstrip("/")
    topic = config.get("topic", "")
    auth_token = config.get("auth", "")

    if not topic:
        raise ValueError("Ntfy topic is required")

    title_text = data.get("item_name", "Unknown")
    series = data.get("series_name")
    if series:
        title_text = f"{series} - {title_text}"

    user = data.get("user_name", "Unknown")
    label = EVENT_LABELS.get(event_type, event_type)

    body_lines = [f"User: {user}", f"Title: {title_text}"]
    if data.get("play_method"):
        body_lines.append(f"Play Method: {data['play_method']}")
    if data.get("client"):
        body_lines.append(f"Platform: {data['client']} ({data.get('device_name', '')})")
    if data.get("duration_seconds"):
        m, s = divmod(data["duration_seconds"], 60)
        h, m = divmod(m, 60)
        dur = f"{h}h {m}m" if h else f"{m}m {s}s"
        body_lines.append(f"Duration: {dur}")
    if data.get("percent_complete"):
        body_lines.append(f"Progress: {data['percent_complete']:.0f}%")

    headers = {
        "Title": f"Empulse: {label}",
        "Tags": EVENT_TAGS.get(event_type, "bell"),
        "Priority": "default",
    }

    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    url = f"{server_url}/{topic}"

    error = validate_outbound_url(url)
    if error:
        raise ValueError(f"Ntfy URL blocked: {error}")

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, content="\n".join(body_lines), headers=headers)
        r.raise_for_status()
