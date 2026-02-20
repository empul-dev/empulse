"""Newsletter system for periodic email summaries."""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosqlite

from empulse.db import stats as stats_db

logger = logging.getLogger("empulse.newsletter")


async def get_newsletter_config(db: aiosqlite.Connection) -> dict | None:
    cursor = await db.execute("SELECT * FROM newsletter_config WHERE id = 1")
    row = await cursor.fetchone()
    return dict(row) if row else None


async def save_newsletter_config(db: aiosqlite.Connection, data: dict):
    existing = await get_newsletter_config(db)
    if existing:
        await db.execute(
            "UPDATE newsletter_config SET enabled=?, schedule=?, day_of_week=?, hour=?, "
            "recently_added_days=?, recently_added_limit=?, include_stats=?, "
            "smtp_host=?, smtp_port=?, smtp_user=?, smtp_pass=?, smtp_tls=?, "
            "from_addr=?, to_addrs=? WHERE id=1",
            [
                1 if data.get("enabled") else 0,
                data.get("schedule", "weekly"),
                int(data.get("day_of_week", 0)),
                int(data.get("hour", 9)),
                int(data.get("recently_added_days", 7)),
                int(data.get("recently_added_limit", 20)),
                1 if data.get("include_stats", True) else 0,
                data.get("smtp_host", ""),
                int(data.get("smtp_port", 587)),
                data.get("smtp_user", ""),
                data.get("smtp_pass", ""),
                1 if data.get("smtp_tls", True) else 0,
                data.get("from_addr", ""),
                data.get("to_addrs", ""),
            ],
        )
    else:
        await db.execute(
            "INSERT INTO newsletter_config (id, enabled, schedule, day_of_week, hour, "
            "recently_added_days, recently_added_limit, include_stats, "
            "smtp_host, smtp_port, smtp_user, smtp_pass, smtp_tls, from_addr, to_addrs) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                1 if data.get("enabled") else 0,
                data.get("schedule", "weekly"),
                int(data.get("day_of_week", 0)),
                int(data.get("hour", 9)),
                int(data.get("recently_added_days", 7)),
                int(data.get("recently_added_limit", 20)),
                1 if data.get("include_stats", True) else 0,
                data.get("smtp_host", ""),
                int(data.get("smtp_port", 587)),
                data.get("smtp_user", ""),
                data.get("smtp_pass", ""),
                1 if data.get("smtp_tls", True) else 0,
                data.get("from_addr", ""),
                data.get("to_addrs", ""),
            ],
        )
    await db.commit()


async def build_newsletter_html(db: aiosqlite.Connection, config: dict, emby_client=None) -> str:
    """Build the newsletter HTML content."""
    days = config.get("recently_added_days", 7)
    limit = config.get("recently_added_limit", 20)
    include_stats = config.get("include_stats", 1)

    # Recently added items from Emby
    recently_added = []
    if emby_client:
        try:
            recently_added = await emby_client.get_recently_added(limit=limit)
        except Exception as e:
            logger.warning(f"Failed to fetch recently added for newsletter: {e}")

    # Stats for the period
    stats_html = ""
    if include_stats:
        total_plays = await stats_db.get_total_plays(db)
        top_users = await stats_db.get_top_users(db, limit=5, days=days)
        most_watched = await stats_db.get_most_watched_movies(db, limit=5, days=days)
        most_watched_shows = await stats_db.get_most_watched_shows(db, limit=5, days=days)

        stats_rows = f"""
        <tr><td style="padding:8px; font-weight:bold">Total Plays</td><td style="padding:8px">{total_plays}</td></tr>
        """

        users_html = ""
        for u in top_users:
            users_html += f'<li>{u.get("user_name", "Unknown")} ({u.get("plays", 0)} plays)</li>'

        movies_html = ""
        for m in most_watched:
            movies_html += f'<li>{m.get("item_name", "Unknown")} ({m.get("plays", 0)} plays)</li>'

        shows_html = ""
        for s in most_watched_shows:
            shows_html += f'<li>{s.get("series_name", "Unknown")} ({s.get("plays", 0)} plays)</li>'

        stats_html = f"""
        <h2 style="color:#3498db; margin-top:30px">Watch Statistics ({days} days)</h2>
        <table style="border-collapse:collapse; width:100%; margin-bottom:20px;">
        {stats_rows}
        </table>
        {"<h3>Top Users</h3><ol>" + users_html + "</ol>" if users_html else ""}
        {"<h3>Most Watched Movies</h3><ol>" + movies_html + "</ol>" if movies_html else ""}
        {"<h3>Most Watched Shows</h3><ol>" + shows_html + "</ol>" if shows_html else ""}
        """

    # Recently added grid
    items_html = ""
    for item in recently_added:
        name = item.get("Name", "Unknown")
        year = item.get("ProductionYear", "")
        item_type = item.get("Type", "")
        date_added = (item.get("DateCreated", "") or "")[:10]
        items_html += f"""
        <div style="display:inline-block; width:140px; margin:8px; vertical-align:top; text-align:center;">
            <div style="background:#2a2a2a; border-radius:6px; padding:10px; height:100%;">
                <div style="font-weight:bold; font-size:13px; margin-bottom:4px;">{name}</div>
                <div style="color:#888; font-size:11px;">{year} &middot; {item_type}</div>
                <div style="color:#666; font-size:10px; margin-top:4px;">Added {date_added}</div>
            </div>
        </div>
        """

    recently_section = ""
    if items_html:
        recently_section = f"""
        <h2 style="color:#3498db; margin-top:30px">Recently Added</h2>
        <div>{items_html}</div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif; background:#1a1a1a; color:#e0e0e0; padding:20px; max-width:700px; margin:0 auto;">
    <h1 style="color:#fff; border-bottom:2px solid #3498db; padding-bottom:10px;">Empulse Newsletter</h1>
    <p style="color:#888;">Report for the last {days} days</p>
    {stats_html}
    {recently_section}
    <hr style="border-color:#333; margin-top:30px;">
    <p style="color:#666; font-size:12px;">Sent by Empulse</p>
</body>
</html>"""
    return html


async def send_newsletter(db: aiosqlite.Connection, config: dict, emby_client=None) -> tuple[bool, str]:
    """Build and send the newsletter. Returns (success, message)."""
    html = await build_newsletter_html(db, config, emby_client)

    smtp_host = config.get("smtp_host", "")
    to_addrs = config.get("to_addrs", "")

    if not smtp_host or not to_addrs:
        return False, "SMTP host and recipient addresses are required"

    recipients = [a.strip() for a in to_addrs.split(",") if a.strip()]
    if not recipients:
        return False, "No recipients configured"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Empulse Newsletter"
    msg["From"] = config.get("from_addr", config.get("smtp_user", ""))
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText("Your email client does not support HTML.", "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        await asyncio.to_thread(
            _smtp_send,
            smtp_host,
            int(config.get("smtp_port", 587)),
            config.get("smtp_user", ""),
            config.get("smtp_pass", ""),
            bool(config.get("smtp_tls", 1)),
            msg["From"],
            recipients,
            msg,
        )
    except Exception as e:
        return False, str(e)

    # Update last_sent timestamp
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("UPDATE newsletter_config SET last_sent = ? WHERE id = 1", [now])
    await db.commit()

    return True, f"Newsletter sent to {len(recipients)} recipient(s)"


def _smtp_send(host, port, user, password, use_tls, from_addr, to_addrs, msg):
    if use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls(context=context)
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())


class NewsletterScheduler:
    """Background task that checks if it's time to send the newsletter."""

    def __init__(self, db_factory, emby_client=None):
        self.get_db = db_factory
        self.emby_client = emby_client

    async def run(self):
        """Run the scheduler loop. Checks once per minute."""
        while True:
            try:
                await self._check_and_send()
            except Exception as e:
                logger.error(f"Newsletter scheduler error: {e}")
            await asyncio.sleep(60)

    async def _check_and_send(self):
        db = self.get_db()
        config = await get_newsletter_config(db)
        if not config or not config.get("enabled"):
            return

        now = datetime.now(timezone.utc)
        schedule = config.get("schedule", "weekly")
        target_hour = config.get("hour", 9)
        target_dow = config.get("day_of_week", 0)  # 0=Monday

        if now.hour != target_hour or now.minute != 0:
            return

        if schedule == "weekly" and now.weekday() != target_dow:
            return
        if schedule == "monthly" and now.day != 1:
            return

        # Check if already sent recently
        last_sent = config.get("last_sent")
        if last_sent:
            try:
                last = datetime.fromisoformat(last_sent)
                if schedule == "daily" and (now - last) < timedelta(hours=23):
                    return
                if schedule == "weekly" and (now - last) < timedelta(days=6):
                    return
                if schedule == "monthly" and (now - last) < timedelta(days=27):
                    return
            except (ValueError, TypeError):
                pass

        success, msg = await send_newsletter(db, config, self.emby_client)
        if success:
            logger.info(f"Newsletter sent: {msg}")
        else:
            logger.error(f"Newsletter send failed: {msg}")
