import csv
import io
import json
import logging
import re
from datetime import date, timedelta
from urllib.parse import quote
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from empulse.app import templates
from empulse.config import settings
from empulse.database import get_db
from empulse.db import history as history_db, stats as stats_db
from empulse.models import SessionInfo, HistoryRecord

logger = logging.getLogger("empulse.api")
router = APIRouter()

VALID_ID = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_id(value: str) -> bool:
    return bool(VALID_ID.match(value)) and len(value) <= 64


@router.get("/now-playing")
async def now_playing(request: Request):
    sessions = []
    state_tracker = getattr(request.app.state, "state_tracker", None)
    if state_tracker:
        sessions = [SessionInfo(**s) for s in state_tracker.get_all_sessions()]
    return templates.TemplateResponse("partials/now_playing.html", {
        "request": request, "sessions": sessions,
    })


def _clamp_days(days: int) -> int:
    return max(1, min(days, 365))


@router.get("/stats-cards")
async def stats_cards(request: Request, days: int = 30, metric: str = "plays"):
    days = _clamp_days(days)
    try:
        return await _stats_cards(request, days, metric)
    except Exception as e:
        logger.exception("stats-cards error")
        return '<p class="empty-state">An internal error occurred.</p>'


async def _stats_cards(request: Request, days: int, metric: str):
    db = get_db()

    state_tracker = getattr(request.app.state, "state_tracker", None)
    active_streams = len(state_tracker.get_all_sessions()) if state_tracker else 0

    most_watched_movies = await stats_db.get_most_watched_movies(db, limit=5, days=days, metric=metric)
    most_popular_movies = await stats_db.get_most_popular_movies(db, limit=5, days=days)
    most_watched_shows = await stats_db.get_most_watched_shows(db, limit=5, days=days, metric=metric)
    most_popular_shows = await stats_db.get_most_popular_shows(db, limit=5, days=days)
    recently_watched = await stats_db.get_recently_watched(db, limit=5)
    most_active_users = await stats_db.get_top_users(db, limit=5, days=days, metric=metric)
    most_active_platforms = await stats_db.get_most_active_platforms(db, limit=5, days=days)
    most_active_libraries = await stats_db.get_most_active_libraries(db, limit=5, days=days)

    # Format recently watched display titles
    for item in recently_watched:
        if item.get("series_name") and item.get("season_number") is not None and item.get("episode_number") is not None:
            item["display_title"] = f"{item['series_name']} - S{item['season_number']:02d}E{item['episode_number']:02d}"
        elif item.get("item_name") and item.get("year"):
            item["display_title"] = f"{item['item_name']} ({item['year']})"
        else:
            item["display_title"] = item.get("item_name") or "Unknown"

    # Map library types to readable names
    type_labels = {"Movie": "Movies", "Episode": "TV Shows", "Audio": "Music"}
    for lib in most_active_libraries:
        lib["label"] = type_labels.get(lib.get("item_type"), lib.get("item_type", "Other"))

    return templates.TemplateResponse("partials/stats_cards.html", {
        "request": request,
        "active_streams": active_streams,
        "most_watched_movies": most_watched_movies,
        "most_popular_movies": most_popular_movies,
        "most_watched_shows": most_watched_shows,
        "most_popular_shows": most_popular_shows,
        "recently_watched": recently_watched,
        "most_active_users": most_active_users,
        "most_active_platforms": most_active_platforms,
        "most_active_libraries": most_active_libraries,
        "days": days,
        "metric": metric,
    })


@router.get("/recent-history")
async def recent_history(request: Request):
    db = get_db()
    rows = await history_db.get_history(db, limit=10)
    records = [HistoryRecord(**r) for r in rows]
    return templates.TemplateResponse("partials/history_table.html", {
        "request": request, "records": records, "page": 1, "total_pages": 1,
        "filter_params": "", "sort_by": "date", "sort_order": "desc",
    })


@router.get("/history-table")
async def history_table(
    request: Request,
    page: int = 1,
    search: str = "",
    user_id: str = "",
    item_type: str = "",
    play_method: str = "",
    sort_by: str = "date",
    sort_order: str = "desc",
):
    db = get_db()
    per_page = 50
    offset = (page - 1) * per_page

    rows = await history_db.get_history(
        db, limit=per_page, offset=offset,
        user_id=user_id or None,
        item_type=item_type or None,
        play_method=play_method or None,
        search=search or None,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = await history_db.get_history_count(
        db, user_id=user_id or None,
        item_type=item_type or None,
        play_method=play_method or None,
        search=search or None,
    )
    records = [HistoryRecord(**r) for r in rows]
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Build filter params for pagination links (URL-encoded)
    filter_params = ""
    if user_id:
        filter_params += f"&user_id={quote(user_id)}"
    if item_type:
        filter_params += f"&item_type={quote(item_type)}"
    if play_method:
        filter_params += f"&play_method={quote(play_method)}"
    if search:
        filter_params += f"&search={quote(search)}"
    if sort_by != "date":
        filter_params += f"&sort_by={quote(sort_by)}"
    if sort_order != "desc":
        filter_params += f"&sort_order={quote(sort_order)}"

    return templates.TemplateResponse("partials/history_table.html", {
        "request": request, "records": records,
        "page": page, "total_pages": total_pages,
        "filter_params": filter_params,
        "sort_by": sort_by, "sort_order": sort_order,
    })


@router.get("/stream-info/{history_id}")
async def stream_info(request: Request, history_id: int):
    db = get_db()
    row = await history_db.get_history_by_id(db, history_id)
    if not row:
        return '<p class="empty-state">Record not found</p>'

    record = HistoryRecord(**row)
    try:
        info = json.loads(record.stream_info) if record.stream_info else {}
    except (json.JSONDecodeError, TypeError):
        info = {}

    return templates.TemplateResponse("partials/stream_info.html", {
        "request": request,
        "record": record,
        "info": info,
    })


@router.get("/history-detail/{history_id}")
async def history_detail(request: Request, history_id: int):
    db = get_db()
    row = await history_db.get_history_by_id(db, history_id)
    if not row:
        return '<p class="empty-state">Record not found</p>'

    record = HistoryRecord(**row)
    try:
        info = json.loads(record.stream_info) if record.stream_info else {}
    except (json.JSONDecodeError, TypeError):
        info = {}

    return templates.TemplateResponse("partials/history_detail.html", {
        "request": request,
        "record": record,
        "info": info,
    })


@router.delete("/history/{history_id}")
async def delete_history(history_id: int):
    db = get_db()
    deleted = await history_db.delete_history(db, history_id)
    if not deleted:
        return Response(status_code=404)
    return Response(status_code=204)


EXPORT_FIELDS = [
    "started_at", "stopped_at", "user_name", "item_name", "series_name",
    "item_type", "duration_seconds", "percent_complete", "play_method",
    "client", "device_name", "ip_address",
]
EXPORT_MAX_ROWS = 10_000


@router.get("/export/history")
async def export_history(
    format: str = "csv",
    user_id: str = "",
    item_type: str = "",
    play_method: str = "",
    search: str = "",
):
    db = get_db()
    rows = await history_db.get_history(
        db, limit=EXPORT_MAX_ROWS, offset=0,
        user_id=user_id or None,
        item_type=item_type or None,
        play_method=play_method or None,
        search=search or None,
        sort_by="date", sort_order="desc",
    )

    if format == "json":
        data = [{k: r.get(k) for k in EXPORT_FIELDS} for r in rows]
        content = json.dumps(data, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=empulse_history.json"},
        )

    # CSV (default)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in EXPORT_FIELDS})

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=empulse_history.csv"},
    )


@router.get("/img/{item_id}")
async def image_proxy(item_id: str, w: int = 150):
    """Proxy Emby item images so the API key stays server-side."""
    if not _validate_id(item_id):
        return Response(content=b"", status_code=400)
    max_width = max(20, min(w, 600))
    import httpx
    url = f"{settings.emby_url.rstrip('/')}/Items/{item_id}/Images/Primary"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"api_key": settings.emby_api_key, "maxWidth": str(max_width)})
            if r.status_code == 200:
                return Response(
                    content=r.content,
                    media_type=r.headers.get("content-type", "image/jpeg"),
                    headers={"Cache-Control": "public, max-age=86400"},
                )
    except Exception:
        pass
    # 1x1 transparent pixel fallback
    return Response(
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/img/backdrop/{item_id}")
async def backdrop_proxy(item_id: str):
    """Proxy Emby item backdrop images."""
    if not _validate_id(item_id):
        return Response(content=b"", status_code=400)
    import httpx
    url = f"{settings.emby_url.rstrip('/')}/Items/{item_id}/Images/Backdrop"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"api_key": settings.emby_api_key, "maxWidth": "1280"})
            if r.status_code == 200:
                return Response(
                    content=r.content,
                    media_type=r.headers.get("content-type", "image/jpeg"),
                    headers={"Cache-Control": "public, max-age=86400"},
                )
    except Exception:
        pass
    return Response(
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/img/user/{user_id}")
async def user_image_proxy(user_id: str):
    """Proxy Emby user images."""
    if not _validate_id(user_id):
        return Response(content=b"", status_code=400)
    import httpx
    url = f"{settings.emby_url.rstrip('/')}/Users/{user_id}/Images/Primary"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"api_key": settings.emby_api_key, "maxWidth": "80"})
            if r.status_code == 200:
                return Response(
                    content=r.content,
                    media_type=r.headers.get("content-type", "image/jpeg"),
                    headers={"Cache-Control": "public, max-age=86400"},
                )
    except Exception:
        pass
    return Response(
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


def _fill_date_gaps(rows: list[dict], days: int) -> list[dict]:
    """Fill missing dates with zeroed entries."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    existing = {r["date"]: r for r in rows}
    result = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        if d in existing:
            result.append(existing[d])
        else:
            result.append({"date": d, "plays": 0, "total_duration": 0})
    return result


@router.get("/charts/daily-plays")
async def chart_daily_plays(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_plays_per_day(db, days=days)
    filled = _fill_date_gaps(rows, days)
    return JSONResponse(filled)


@router.get("/charts/plays-by-type")
async def chart_plays_by_type(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_plays_by_type(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/plays-by-platform")
async def chart_plays_by_platform(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_most_active_platforms(db, limit=10, days=days)
    return JSONResponse(rows)


@router.get("/charts/user/{user_id}/daily-plays")
async def chart_user_daily_plays(user_id: str, days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_user_plays_per_day(db, user_id, days=days)
    filled = _fill_date_gaps(rows, days)
    return JSONResponse(filled)


@router.get("/charts/user/{user_id}/by-type")
async def chart_user_by_type(user_id: str, days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_user_plays_by_type(db, user_id, days=days)
    return JSONResponse(rows)


@router.get("/charts/library/{item_type}/daily-plays")
async def chart_library_daily_plays(item_type: str, days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_library_plays_per_day(db, item_type, days=days)
    filled = _fill_date_gaps(rows, days)
    return JSONResponse(filled)


@router.get("/recently-added")
async def recently_added(request: Request, limit: int = 10, item_type: str = ""):
    emby_client = getattr(request.app.state, "emby_client", None)
    if not emby_client:
        return templates.TemplateResponse("partials/recently_added.html", {
            "request": request, "items": [],
        })
    limit = max(1, min(limit, 20))
    try:
        items = await emby_client.get_recently_added(limit=limit, item_type=item_type)
    except Exception as e:
        logger.error(f"Recently added fetch failed: {e}")
        items = []
    return templates.TemplateResponse("partials/recently_added.html", {
        "request": request, "items": items,
    })


@router.get("/charts/plays-by-date-stacked")
async def chart_plays_by_date_stacked(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_plays_by_date_stacked(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/plays-by-dow")
async def chart_plays_by_dow(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_plays_by_day_of_week(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/plays-by-hour")
async def chart_plays_by_hour(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_plays_by_hour(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/plays-per-month")
async def chart_plays_per_month(months: int = 12):
    months = max(1, min(months, 36))
    db = get_db()
    rows = await stats_db.get_plays_per_month(db, months=months)
    return JSONResponse(rows)


@router.get("/charts/plays-by-stream-type")
async def chart_plays_by_stream_type(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_plays_by_stream_type(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/source-resolution")
async def chart_source_resolution(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_source_resolution_distribution(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/transcode-ratio")
async def chart_transcode_ratio(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_transcode_ratio(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/top-platforms-stream-type")
async def chart_top_platforms_stream_type(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_top_platforms_with_stream_type(db, days=days)
    return JSONResponse(rows)


@router.get("/charts/top-users-stream-type")
async def chart_top_users_stream_type(days: int = 30):
    days = _clamp_days(days)
    db = get_db()
    rows = await stats_db.get_top_users_with_stream_type(db, days=days)
    return JSONResponse(rows)


@router.get("/notification-channels")
async def list_notification_channels():
    db = get_db()
    cursor = await db.execute("SELECT * FROM notification_channels ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    return JSONResponse([dict(r) for r in rows])


@router.post("/notification-channels")
async def create_notification_channel(request: Request):
    data = await request.json()
    db = get_db()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO notification_channels (name, channel_type, config, triggers, conditions, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            data.get("name", ""),
            data.get("channel_type", ""),
            json.dumps(data.get("config", {})),
            json.dumps(data.get("triggers", [])),
            json.dumps(data.get("conditions", {})),
            1 if data.get("enabled", True) else 0,
            now,
        ],
    )
    await db.commit()
    engine = getattr(request.app.state, "notification_engine", None)
    if engine:
        engine.invalidate_cache()
    return JSONResponse({"status": "created"}, status_code=201)


@router.put("/notification-channels/{channel_id}")
async def update_notification_channel(request: Request, channel_id: int):
    data = await request.json()
    db = get_db()
    cursor = await db.execute("SELECT id FROM notification_channels WHERE id = ?", [channel_id])
    if not await cursor.fetchone():
        return Response(status_code=404)
    await db.execute(
        "UPDATE notification_channels SET name=?, channel_type=?, config=?, triggers=?, conditions=?, enabled=? WHERE id=?",
        [
            data.get("name", ""),
            data.get("channel_type", ""),
            json.dumps(data.get("config", {})),
            json.dumps(data.get("triggers", [])),
            json.dumps(data.get("conditions", {})),
            1 if data.get("enabled", True) else 0,
            channel_id,
        ],
    )
    await db.commit()
    engine = getattr(request.app.state, "notification_engine", None)
    if engine:
        engine.invalidate_cache()
    return JSONResponse({"status": "updated"})


@router.delete("/notification-channels/{channel_id}")
async def delete_notification_channel(request: Request, channel_id: int):
    db = get_db()
    cursor = await db.execute("DELETE FROM notification_channels WHERE id = ?", [channel_id])
    await db.commit()
    if cursor.rowcount == 0:
        return Response(status_code=404)
    engine = getattr(request.app.state, "notification_engine", None)
    if engine:
        engine.invalidate_cache()
    return Response(status_code=204)


@router.post("/notification-channels/{channel_id}/test")
async def test_notification_channel(request: Request, channel_id: int):
    db = get_db()
    cursor = await db.execute("SELECT * FROM notification_channels WHERE id = ?", [channel_id])
    row = await cursor.fetchone()
    if not row:
        return Response(status_code=404)
    engine = getattr(request.app.state, "notification_engine", None)
    if not engine:
        return JSONResponse({"success": False, "message": "Notification engine not initialized"})
    success, message = await engine.send_test(dict(row))
    return JSONResponse({"success": success, "message": message})


@router.get("/notification-log")
async def notification_log():
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM notification_log ORDER BY sent_at DESC LIMIT 50"
    )
    rows = await cursor.fetchall()
    return JSONResponse([dict(r) for r in rows])


@router.get("/newsletter/config")
async def get_newsletter_config_api():
    db = get_db()
    from empulse.newsletter import get_newsletter_config
    config = await get_newsletter_config(db)
    return JSONResponse(config or {})


@router.post("/newsletter/config")
async def save_newsletter_config_api(request: Request):
    data = await request.json()
    db = get_db()
    from empulse.newsletter import save_newsletter_config
    await save_newsletter_config(db, data)
    return JSONResponse({"status": "saved"})


@router.get("/newsletter/preview")
async def newsletter_preview(request: Request):
    db = get_db()
    from empulse.newsletter import get_newsletter_config, build_newsletter_html
    config = await get_newsletter_config(db)
    if not config:
        config = {"recently_added_days": 7, "recently_added_limit": 20, "include_stats": 1}
    emby_client = getattr(request.app.state, "emby_client", None)
    html = await build_newsletter_html(db, config, emby_client)
    return Response(content=html, media_type="text/html")


@router.post("/newsletter/send")
async def send_newsletter_now(request: Request):
    db = get_db()
    from empulse.newsletter import get_newsletter_config, send_newsletter
    config = await get_newsletter_config(db)
    if not config:
        return JSONResponse({"success": False, "message": "Newsletter not configured"}, status_code=400)
    emby_client = getattr(request.app.state, "emby_client", None)
    success, message = await send_newsletter(db, config, emby_client)
    return JSONResponse({"success": success, "message": message})


@router.get("/backup")
async def backup_database():
    from pathlib import Path
    db_path = Path(settings.db_path)
    if not db_path.exists() or str(db_path) == ":memory:":
        return Response(content="Database not available for backup", status_code=400)

    return Response(
        content=db_path.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=empulse_backup.db"},
    )


@router.post("/restore")
async def restore_database(request: Request):
    from pathlib import Path
    import shutil

    db_path = Path(settings.db_path)
    if str(db_path) == ":memory:":
        return JSONResponse({"error": "Cannot restore to in-memory database"}, status_code=400)

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return JSONResponse({"error": "Upload a .db file"}, status_code=400)

    form = await request.form()
    upload = form.get("file")
    if not upload:
        return JSONResponse({"error": "No file uploaded"}, status_code=400)

    data = await upload.read()
    # Basic SQLite validation: check magic header
    if not data[:16].startswith(b"SQLite format 3"):
        return JSONResponse({"error": "Invalid SQLite database file"}, status_code=400)

    # Size limit: 500MB
    if len(data) > 500 * 1024 * 1024:
        return JSONResponse({"error": "File too large (max 500MB)"}, status_code=400)

    # Create backup of current DB before replacing
    backup_path = db_path.with_suffix(".db.bak")
    if db_path.exists():
        shutil.copy2(str(db_path), str(backup_path))

    # Write new DB
    db_path.write_bytes(data)
    return JSONResponse({"status": "restored", "message": "Database restored. Restart the application to apply changes."})


@router.get("/random-posters")
async def random_posters(request: Request, limit: int = 24):
    """Return random item IDs from Emby for the login poster wall."""
    emby_client = getattr(request.app.state, "emby_client", None)
    if not emby_client:
        return JSONResponse([])
    limit = max(1, min(limit, 48))
    try:
        params = {
            **emby_client._params,
            "SortBy": "Random",
            "Recursive": "true",
            "Limit": str(limit),
            "IncludeItemTypes": "Movie,Series",
            "ImageTypes": "Primary",
            "Fields": "PrimaryImageAspectRatio",
        }
        r = await emby_client._client.get(
            f"{emby_client.base_url}/Items", params=params
        )
        r.raise_for_status()
        items = r.json().get("Items", [])
        ids = [item["Id"] for item in items if item.get("Id")]
        return JSONResponse(ids, headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:
        logger.warning(f"Random posters fetch failed: {e}")
        return JSONResponse([])


@router.post("/test-connection")
async def test_connection(request: Request):
    emby_client = getattr(request.app.state, "emby_client", None)
    if not emby_client:
        from empulse.emby.client import EmbyClient
        emby_client = EmbyClient()

    try:
        info = await emby_client.get_server_info()
        db = get_db()
        from empulse.db.libraries import upsert_server_info
        await upsert_server_info(db, {
            "server_name": info.get("ServerName", ""),
            "version": info.get("Version", ""),
            "local_address": info.get("LocalAddress", ""),
            "wan_address": info.get("WanAddress", ""),
            "os": info.get("OperatingSystem", ""),
        })
        from markupsafe import escape
        return f'<p class="success">Connected to {escape(info.get("ServerName", "Emby"))} v{escape(info.get("Version", "?"))}</p>'
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return '<p class="error">Connection failed. Check server logs for details.</p>'
