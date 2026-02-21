import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

logger = logging.getLogger("empulse.notifications.email")

EVENT_LABELS = {
    "playback_start": "Playback Started",
    "playback_stop": "Playback Stopped",
    "playback_pause": "Playback Paused",
    "playback_resume": "Playback Resumed",
    "watched": "Watched",
    "transcode": "Transcode Detected",
}


def _build_title(event_type: str, data: dict) -> str:
    title = data.get("item_name", "Unknown")
    series = data.get("series_name")
    if series:
        title = f"{series} - {title}"
    return title


def _build_plain(event_type: str, data: dict) -> str:
    label = EVENT_LABELS.get(event_type, event_type)
    title = _build_title(event_type, data)
    user = data.get("user_name", "Unknown")
    lines = [
        f"{label}",
        f"",
        f"User: {user}",
        f"Title: {title}",
    ]
    if data.get("play_method"):
        lines.append(f"Play Method: {data['play_method']}")
    if data.get("client"):
        lines.append(f"Platform: {data['client']} ({data.get('device_name', '')})")
    if data.get("duration_seconds"):
        m, s = divmod(data["duration_seconds"], 60)
        h, m = divmod(m, 60)
        dur = f"{h}h {m}m" if h else f"{m}m {s}s"
        lines.append(f"Duration: {dur}")
    if data.get("percent_complete"):
        lines.append(f"Progress: {data['percent_complete']:.0f}%")
    return "\n".join(lines)


def _build_html(event_type: str, data: dict) -> str:
    label = escape(EVENT_LABELS.get(event_type, event_type))
    title = escape(_build_title(event_type, data))
    user = escape(data.get("user_name", "Unknown"))

    rows = [
        f"<tr><td><b>User</b></td><td>{user}</td></tr>",
        f"<tr><td><b>Title</b></td><td>{title}</td></tr>",
    ]
    if data.get("play_method"):
        rows.append(f"<tr><td><b>Play Method</b></td><td>{escape(str(data['play_method']))}</td></tr>")
    if data.get("client"):
        rows.append(f"<tr><td><b>Platform</b></td><td>{escape(str(data['client']))} ({escape(str(data.get('device_name', '')))})</td></tr>")
    if data.get("duration_seconds"):
        m, s = divmod(data["duration_seconds"], 60)
        h, m = divmod(m, 60)
        dur = f"{h}h {m}m" if h else f"{m}m {s}s"
        rows.append(f"<tr><td><b>Duration</b></td><td>{dur}</td></tr>")
    if data.get("percent_complete"):
        rows.append(f"<tr><td><b>Progress</b></td><td>{data['percent_complete']:.0f}%</td></tr>")

    table_rows = "\n".join(rows)
    return f"""<html><body>
<h2 style="color:#3498db">{label}</h2>
<table style="border-collapse:collapse; font-family:sans-serif;">
{table_rows}
</table>
<hr><p style="color:#888; font-size:12px">Sent by Empulse</p>
</body></html>"""


async def send_email(config: dict, event_type: str, data: dict):
    smtp_host = config.get("smtp_host", "")
    smtp_port = int(config.get("smtp_port", 587))
    smtp_user = config.get("smtp_user", "")
    smtp_pass = config.get("smtp_pass", "")
    use_tls = config.get("tls", True)
    from_addr = config.get("from_addr", smtp_user)
    to_addr = config.get("to_addr", "")

    if not smtp_host or not to_addr:
        raise ValueError("SMTP host and recipient address are required")

    label = EVENT_LABELS.get(event_type, event_type)
    title = _build_title(event_type, data)
    subject = f"Empulse: {label} — {title}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    msg.attach(MIMEText(_build_plain(event_type, data), "plain"))
    msg.attach(MIMEText(_build_html(event_type, data), "html"))

    # Run SMTP in thread to avoid blocking the event loop
    import asyncio
    await asyncio.to_thread(_smtp_send, smtp_host, smtp_port, smtp_user, smtp_pass, use_tls, from_addr, to_addr, msg)


def _smtp_send(host, port, user, password, use_tls, from_addr, to_addr, msg):
    if use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls(context=context)
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
