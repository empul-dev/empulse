"""Scrub secrets out of notification error strings before they hit logs or
the notification_log DB table."""

import re

# Query-string-style secret params: token=..., key=..., password=..., etc.
_PARAM_RE = re.compile(
    r"(?i)\b(token|key|password|pass|secret|auth)=([^&\s\"'>]+)"
)

# Telegram Bot API URLs embed the bot token directly in the path:
# https://api.telegram.org/bot<token>/sendMessage
_TELEGRAM_BOT_RE = re.compile(r"/bot[0-9]+:[A-Za-z0-9_-]+")

# Discord/generic webhook URLs commonly embed a token/id path segment after
# .../webhooks/<id>/<token>
_DISCORD_WEBHOOK_RE = re.compile(
    r"(discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_-]+"
)


def scrub(text: str) -> str:
    """Redact secrets (query-string tokens, bot tokens, webhook tokens) from
    a free-text error/log message."""
    if not text:
        return text
    text = _PARAM_RE.sub(lambda m: f"{m.group(1)}=***", text)
    text = _TELEGRAM_BOT_RE.sub("/bot***", text)
    text = _DISCORD_WEBHOOK_RE.sub(r"\1***", text)
    return text
