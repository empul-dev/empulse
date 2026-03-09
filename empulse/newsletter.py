"""Newsletter system for periodic email summaries."""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import aiosqlite

from empulse.db import stats as stats_db

logger = logging.getLogger("empulse.newsletter")


async def get_newsletter_config(db: aiosqlite.Connection) -> dict | None:
    cursor = await db.execute("SELECT * FROM newsletter_config WHERE id = 1")
    row = await cursor.fetchone()
    return dict(row) if row else None


async def save_newsletter_config(db: aiosqlite.Connection, data: dict):
    existing = await get_newsletter_config(db)
    # Preserve existing password if masked placeholder is sent back
    if data.get("smtp_pass") == "***" and existing:
        data = {**data, "smtp_pass": existing.get("smtp_pass", "")}
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


def _format_runtime(ticks: int | None) -> str:
    if not ticks:
        return ""
    mins = int(ticks / 600_000_000)
    return f"{mins} mins" if mins > 0 else ""


def _stars_html(rating: float | int | None) -> str:
    if rating is None:
        return ""
    try:
        stars = max(0, min(5, round(float(rating) / 2)))
    except (TypeError, ValueError):
        return ""
    filled = "&#9733;" * stars
    empty = "&#9734;" * (5 - stars)
    return (
        '<div style="font-size:18px; line-height:1; color:#eab308; '
        'letter-spacing:1px; white-space:nowrap;">'
        f"{filled}<span style=\"color:#666;\">{empty}</span></div>"
    )


def _badge_html(text: str) -> str:
    if not text:
        return ""
    return (
        '<span style="display:inline-block; margin:0 8px 8px 0; padding:8px 12px; '
        'border-radius:8px; background:rgba(26,26,26,0.92); color:#e0e0e0; '
        'font-size:14px; line-height:1;">'
        f"{escape(text)}</span>"
    )


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _truncate(value: str | None, limit: int) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _pick_summary(item: dict, fallback_limit: int = 320) -> str:
    taglines = item.get("Taglines") or []
    tagline = _normalize_text(str(taglines[0])) if taglines else ""
    overview = _truncate(str(item.get("Overview", "")), fallback_limit)
    if tagline and overview:
        return (
            f'<p style="margin:0 0 16px; color:#e0e0e0; font-size:18px; '
            f'line-height:1.4; font-style:italic;">{escape(tagline)}</p>'
            f'<p style="margin:0; color:#e0e0e0; font-size:16px; line-height:1.5;">'
            f"{escape(overview)}</p>"
        )
    if tagline:
        return (
            '<p style="margin:0; color:#e0e0e0; font-size:18px; line-height:1.4; '
            f'font-style:italic;">{escape(tagline)}</p>'
        )
    if overview:
        return (
            '<p style="margin:0; color:#e0e0e0; font-size:16px; line-height:1.5;">'
            f"{escape(overview)}</p>"
        )
    return (
        '<p style="margin:0; color:#999; font-size:15px; line-height:1.5;">'
        "No description available.</p>"
    )


def _movie_meta_badges(item: dict) -> str:
    badges = []
    if item.get("ProductionYear"):
        badges.append(_badge_html(str(item["ProductionYear"])))
    runtime = _format_runtime(item.get("RunTimeTicks"))
    if runtime:
        badges.append(_badge_html(runtime))
    for genre in (item.get("Genres") or [])[:2]:
        badges.append(_badge_html(str(genre)))
    return "".join(badges)


def _episode_range_label_html(episodes: list[dict]) -> str:
    newest = episodes[0]
    season = newest.get("ParentIndexNumber")
    if len(episodes) == 1:
        episode_no = newest.get("IndexNumber")
        title = escape(_normalize_text(str(newest.get("Name", ""))))
        parts = []
        if season is not None:
            parts.append(f"Season {season}")
        if episode_no is not None:
            parts.append(f"Episode {episode_no}")
        label = " &middot; ".join(parts)
        if title:
            return f"{label} - {title}" if label else title
        return label

    episode_numbers = [
        ep.get("IndexNumber") for ep in episodes
        if ep.get("ParentIndexNumber") == season and ep.get("IndexNumber") is not None
    ]
    if (
        season is not None
        and len(episode_numbers) == len(episodes)
        and episode_numbers
    ):
        ordered = sorted(int(number) for number in episode_numbers)
        if len(ordered) == 1:
            return f"Season {season} &middot; Episode {ordered[0]}"
        return f"Season {season} &middot; Episodes {ordered[0]:02d}-{ordered[-1]:02d}"
    return f"{len(episodes)} recent episodes"


def _group_tv_items(items: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for item in items:
        if item.get("Type") != "Episode":
            continue
        key = str(
            item.get("SeriesId")
            or item.get("SeriesName")
            or item.get("Id")
            or f"episode-{len(groups)}"
        )
        groups.setdefault(key, []).append(item)

    result = []
    for episodes in groups.values():
        episodes.sort(key=lambda ep: ep.get("DateCreated", ""), reverse=True)
        lead = episodes[0]
        result.append(
            {
                "series_name": str(lead.get("SeriesName") or lead.get("Name") or "Unknown"),
                "series_id": str(lead.get("SeriesId") or lead.get("Id") or ""),
                "episodes": episodes,
                "episode_count": len(episodes),
                "display_count": f"{len(episodes)} episode" + ("" if len(episodes) == 1 else "s"),
                "episode_label_html": _episode_range_label_html(episodes),
                "summary_html": _pick_summary(lead, fallback_limit=280),
                "meta_badges": _movie_meta_badges(lead),
                "rating_html": _stars_html(lead.get("CommunityRating")),
                "year": lead.get("ProductionYear"),
                "runtime": _format_runtime(lead.get("RunTimeTicks")),
                "genres": (lead.get("Genres") or [])[:2],
            }
        )
    result.sort(key=lambda group: group["episodes"][0].get("DateCreated", ""), reverse=True)
    return result


async def _get_image_data_url(
    emby_client,
    item_id: str,
    image_type: str,
    max_width: int,
    cache: dict[tuple[str, str, int], str],
) -> str:
    if not emby_client or not item_id or not hasattr(emby_client, "get_image_data_url"):
        return ""
    cache_key = (item_id, image_type, max_width)
    if cache_key in cache:
        return cache[cache_key]
    try:
        image = await emby_client.get_image_data_url(
            item_id,
            image_type=image_type,
            max_width=max_width,
        )
    except Exception as exc:
        logger.debug("Newsletter image fetch failed for %s (%s): %s", item_id, image_type, exc)
        image = ""
    cache[cache_key] = image
    return image


async def _render_movie_cards(movies: list[dict], emby_client) -> str:
    image_cache: dict[tuple[str, str, int], str] = {}
    cards = []
    for item in movies:
        name = escape(str(item.get("Name", "Unknown")))
        poster_url = await _get_image_data_url(
            emby_client,
            str(item.get("Id", "")),
            "Primary",
            300,
            image_cache,
        )
        backdrop_url = await _get_image_data_url(
            emby_client,
            str(item.get("Id", "")),
            "Backdrop",
            900,
            image_cache,
        )
        background_style = (
            f"background-image:url('{backdrop_url}'); background-size:cover; "
            "background-position:center center;"
            if backdrop_url
            else "background:linear-gradient(135deg, #1c1c1e 0%, #101010 100%);"
        )
        poster_html = (
            f'<td width="180" valign="top" style="padding:0;">'
            f'<img src="{poster_url}" alt="{name}" width="180" '
            'style="display:block; width:180px; height:auto; border:0; object-fit:cover;">'
            "</td>"
            if poster_url
            else ""
        )
        cards.append(
            f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                style="margin:0 0 16px; border-collapse:separate; border-spacing:0; background:#1c1c1e;
                border:1px solid #2a2a2a;">
                <tr>
                    <td style="{background_style}">
                        <div style="background:rgba(16,16,16,0.78);">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    {poster_html}
                                    <td valign="top" style="padding:18px 18px 12px;">
                                        <div style="font-size:18px; line-height:1.3; color:#e0e0e0; margin:0 0 14px;">
                                            {name}
                                        </div>
                                        {_pick_summary(item)}
                                        <div style="padding-top:18px;">
                                            {_movie_meta_badges(item)}
                                            {_stars_html(item.get("CommunityRating"))}
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </div>
                    </td>
                </tr>
            </table>
            """
        )
    return "".join(cards)


async def _render_tv_cards(groups: list[dict], emby_client) -> str:
    image_cache: dict[tuple[str, str, int], str] = {}
    cards = []
    for group in groups:
        series_id = group["series_id"]
        series_name = escape(group["series_name"])
        poster_url = await _get_image_data_url(
            emby_client,
            series_id,
            "Primary",
            300,
            image_cache,
        )
        backdrop_url = await _get_image_data_url(
            emby_client,
            series_id,
            "Backdrop",
            900,
            image_cache,
        )
        background_style = (
            f"background-image:url('{backdrop_url}'); background-size:cover; "
            "background-position:center center;"
            if backdrop_url
            else "background:linear-gradient(135deg, #1c1c1e 0%, #101010 100%);"
        )
        episode_count = escape(group["display_count"])
        episode_label = group["episode_label_html"]
        poster_html = (
            f'<td width="180" valign="top" style="padding:0;">'
            f'<img src="{poster_url}" alt="{series_name}" width="180" '
            'style="display:block; width:180px; height:auto; border:0; object-fit:cover;">'
            "</td>"
            if poster_url
            else ""
        )
        cards.append(
            f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                style="margin:0 0 16px; border-collapse:separate; border-spacing:0; background:#1c1c1e;
                border:1px solid #2a2a2a;">
                <tr>
                    <td style="{background_style}">
                        <div style="background:rgba(16,16,16,0.80);">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    {poster_html}
                                    <td valign="top" style="padding:18px 18px 12px;">
                                        <div style="font-size:18px; line-height:1.3; color:#e0e0e0; margin:0 0 10px;">
                                            {series_name}
                                        </div>
                                        <div style="font-size:14px; line-height:1.3; color:#e0e0e0; margin:0 0 6px; font-weight:bold;">
                                            {episode_count}
                                        </div>
                                        <div style="font-size:15px; line-height:1.4; color:#999; margin:0 0 16px;">
                                            {episode_label}
                                        </div>
                                        {group["summary_html"]}
                                        <div style="padding-top:18px;">
                                            {group["meta_badges"]}
                                            {group["rating_html"]}
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </div>
                    </td>
                </tr>
            </table>
            """
        )
    return "".join(cards)


def _render_stats_section(
    days: int,
    total_plays: int,
    top_users: list[dict],
    most_watched: list[dict],
    most_watched_shows: list[dict],
) -> str:
    users_html = "".join(
        f'<li style="margin:0 0 8px;">{escape(str(u.get("user_name", "Unknown")))} '
        f'({int(u.get("plays", 0))} plays)</li>'
        for u in top_users
    )
    movies_html = "".join(
        f'<li style="margin:0 0 8px;">{escape(str(m.get("item_name", "Unknown")))} '
        f'({int(m.get("plays", 0))} plays)</li>'
        for m in most_watched
    )
    shows_html = "".join(
        f'<li style="margin:0 0 8px;">{escape(str(s.get("series_name", "Unknown")))} '
        f'({int(s.get("plays", 0))} plays)</li>'
        for s in most_watched_shows
    )
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
        style="margin:28px 0 0; background:#1a1a1a; border:1px solid #2a2a2a;">
        <tr>
            <td style="padding:22px;">
                <div style="font-size:26px; line-height:1.2; color:#e0e0e0; margin:0 0 8px;">
                    Watch Statistics
                </div>
                <div style="font-size:14px; line-height:1.5; color:#999; margin:0 0 18px;">
                    Last {days} days
                </div>
                <div style="font-size:34px; line-height:1; color:#52b54b; margin:0 0 18px;">
                    {int(total_plays)}
                </div>
                <div style="font-size:14px; line-height:1.3; color:#999; margin:0 0 18px;">
                    total plays
                </div>
                {"<div style='font-size:16px; color:#e0e0e0; margin:0 0 8px;'>Top Users</div><ol style='margin:0 0 18px 20px; padding:0; color:#e0e0e0;'>" + users_html + "</ol>" if users_html else ""}
                {"<div style='font-size:16px; color:#e0e0e0; margin:0 0 8px;'>Most Watched Movies</div><ol style='margin:0 0 18px 20px; padding:0; color:#e0e0e0;'>" + movies_html + "</ol>" if movies_html else ""}
                {"<div style='font-size:16px; color:#e0e0e0; margin:0 0 8px;'>Most Watched Shows</div><ol style='margin:0 0 0 20px; padding:0; color:#e0e0e0;'>" + shows_html + "</ol>" if shows_html else ""}
            </td>
        </tr>
    </table>
    """


async def build_newsletter_html(db: aiosqlite.Connection, config: dict, emby_client=None) -> str:
    """Build the newsletter HTML content."""
    days = config.get("recently_added_days", 7)
    limit = config.get("recently_added_limit", 20)
    include_stats = config.get("include_stats", 1)

    recently_added: list[dict] = []
    if emby_client:
        try:
            recently_added = await emby_client.get_recently_added(limit=limit)
        except Exception as exc:
            logger.warning("Failed to fetch recently added for newsletter: %s", exc)

    movies = [item for item in recently_added if item.get("Type") == "Movie"]
    tv_groups = _group_tv_items(recently_added)

    movies_html = await _render_movie_cards(movies, emby_client) if movies else ""
    tv_html = await _render_tv_cards(tv_groups, emby_client) if tv_groups else ""

    recently_sections = ""
    if movies_html:
        movie_count = f"{len(movies)} movie" + ("" if len(movies) == 1 else "s")
        recently_sections += f"""
        <div style="padding:32px 28px 8px;">
            <div style="font-size:30px; line-height:1.15; color:#e0e0e0; text-align:center; margin:0 0 12px;">
                Recently Added Movies
            </div>
            <div style="font-size:18px; line-height:1.2; color:#52b54b; text-align:center; margin:0 0 20px; text-transform:uppercase; letter-spacing:1px;">
                {movie_count}
            </div>
            {movies_html}
        </div>
        """

    if tv_html:
        show_count = len(tv_groups)
        episode_total = sum(group["episode_count"] for group in tv_groups)
        show_label = f"{show_count} show" + ("" if show_count == 1 else "s")
        episode_label = f"{episode_total} episode" + ("" if episode_total == 1 else "s")
        recently_sections += f"""
        <div style="padding:8px 28px 24px;">
            <div style="font-size:30px; line-height:1.15; color:#e0e0e0; text-align:center; margin:0 0 12px;">
                Recently Added TV Shows
            </div>
            <div style="font-size:18px; line-height:1.2; color:#52b54b; text-align:center; margin:0 0 20px; text-transform:uppercase; letter-spacing:1px;">
                {show_label} / {episode_label}
            </div>
            {tv_html}
        </div>
        """

    stats_html = ""
    if include_stats:
        total_plays = await stats_db.get_total_plays(db)
        top_users = await stats_db.get_top_users(db, limit=5, days=days)
        most_watched = await stats_db.get_most_watched_movies(db, limit=5, days=days)
        most_watched_shows = await stats_db.get_most_watched_shows(db, limit=5, days=days)
        stats_html = _render_stats_section(
            days,
            total_plays,
            top_users,
            most_watched,
            most_watched_shows,
        )

    empty_html = ""
    if not recently_sections:
        empty_html = """
        <div style="padding:28px 28px 34px; text-align:center;">
            <div style="font-size:24px; line-height:1.3; color:#e0e0e0; margin:0 0 12px;">
                No recently added media
            </div>
            <div style="font-size:16px; line-height:1.5; color:#999; margin:0;">
                Emby did not return any new movies or TV episodes for this newsletter.
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Empulse Newsletter</title>
</head>
<body style="margin:0; padding:0; background:#101010; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#e0e0e0;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0;">
        Empulse Newsletter for the last {days} days
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#101010;">
        <tr>
            <td align="center" style="padding:28px 12px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                    style="max-width:960px; background:#1a1a1a;">
                    <tr>
                        <td style="padding:28px 28px 10px; text-align:center; border-bottom:1px solid #2a2a2a;">
                            <div style="font-size:34px; line-height:1.1; color:#e0e0e0; margin:0 0 8px;">
                                Empulse Newsletter
                            </div>
                            <div style="font-size:15px; line-height:1.5; color:#999; margin:0;">
                                Report for the last {days} days
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td>
                            {recently_sections or empty_html}
                            {stats_html}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:22px 28px 28px; border-top:1px solid #2a2a2a;">
                            <div style="font-size:12px; line-height:1.5; color:#666;">
                                Sent by Empulse
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
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
    except Exception as exc:
        return False, str(exc)

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
            except Exception as exc:
                logger.error("Newsletter scheduler error: %s", exc)
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

        last_sent = config.get("last_sent")
        if last_sent:
            try:
                last = datetime.fromisoformat(last_sent)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if now - last < timedelta(hours=23):
                    return
            except Exception:
                pass

        success, msg = await send_newsletter(db, config, self.emby_client)
        if success:
            logger.info(msg)
        else:
            logger.error("Newsletter send failed: %s", msg)
