import json
import httpx


async def send_webhook(config: dict, event_type: str, data: dict):
    url = config.get("url", "")
    if not url:
        raise ValueError("Webhook URL not configured")

    method = config.get("method", "POST").upper()
    if method not in ("POST", "PUT"):
        method = "POST"

    headers = config.get("headers", {})
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except (json.JSONDecodeError, TypeError):
            headers = {}

    # Build body - support template placeholders
    body_template = config.get("body")
    if body_template and isinstance(body_template, str):
        body = _apply_template(body_template, event_type, data)
        content_type = headers.get("Content-Type", "application/json")
        if "json" in content_type:
            try:
                # Validate it's valid JSON
                json.loads(body)
            except (json.JSONDecodeError, TypeError):
                pass
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request(
                method, url, content=body.encode(),
                headers={"Content-Type": content_type, **headers},
            )
            r.raise_for_status()
    else:
        # Default: send full event data as JSON
        payload = {
            "event": event_type,
            "user_name": data.get("user_name"),
            "item_name": data.get("item_name"),
            "item_type": data.get("item_type"),
            "series_name": data.get("series_name"),
            "play_method": data.get("play_method"),
            "client": data.get("client"),
            "device_name": data.get("device_name"),
            "duration_seconds": data.get("duration_seconds"),
            "percent_complete": data.get("percent_complete"),
            "ip_address": data.get("ip_address"),
        }
        final_headers = {"Content-Type": "application/json"}
        final_headers.update(headers)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request(method, url, json=payload, headers=final_headers)
            r.raise_for_status()


def _apply_template(template: str, event_type: str, data: dict) -> str:
    replacements = {
        "{event}": event_type,
        "{user}": data.get("user_name", ""),
        "{title}": data.get("item_name", ""),
        "{series}": data.get("series_name", ""),
        "{type}": data.get("item_type", ""),
        "{play_method}": data.get("play_method", ""),
        "{client}": data.get("client", ""),
        "{device}": data.get("device_name", ""),
        "{duration}": str(data.get("duration_seconds", 0)),
        "{percent}": str(data.get("percent_complete", 0)),
        "{ip}": data.get("ip_address", ""),
    }
    result = template
    for key, value in replacements.items():
        result = result.replace(key, str(value) if value is not None else "")
    return result
