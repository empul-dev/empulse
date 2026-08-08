import json
import re

import httpx

from empulse.notifications.url_validator import validate_outbound_url

# Only these placeholders are ever expanded (E-5: fixed whitelist).
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


async def send_webhook(config: dict, event_type: str, data: dict):
    url = config.get("url", "")
    if not url:
        raise ValueError("Webhook URL not configured")

    error = validate_outbound_url(url)
    if error:
        raise ValueError(f"Webhook URL blocked: {error}")

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
        content_type = headers.get("Content-Type", "application/json")
        json_mode = "json" in content_type
        body = _apply_template(body_template, event_type, data, json_mode=json_mode)
        if json_mode:
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


def _apply_template(
    template: str, event_type: str, data: dict, *, json_mode: bool = False
) -> str:
    """Expand {placeholder} tokens from a fixed whitelist in a single pass.

    Single pass (one re.sub) means substituted values are never re-scanned, so a
    user-controlled value like a username of "{ip}" cannot expand into another
    field (E-5 template confusion). In json_mode each value is JSON-escaped so a
    value containing '"' can't break out of its JSON string.
    """
    values = {
        "event": event_type,
        "user": data.get("user_name", ""),
        "title": data.get("item_name", ""),
        "series": data.get("series_name", ""),
        "type": data.get("item_type", ""),
        "play_method": data.get("play_method", ""),
        "client": data.get("client", ""),
        "device": data.get("device_name", ""),
        "duration": data.get("duration_seconds", 0),
        "percent": data.get("percent_complete", 0),
        "ip": data.get("ip_address", ""),
    }

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            return m.group(0)  # leave unknown placeholders untouched
        val = values[key]
        val = "" if val is None else str(val)
        if json_mode:
            val = json.dumps(val)[1:-1]  # escape without the surrounding quotes
        return val

    return _PLACEHOLDER_RE.sub(_sub, template)
