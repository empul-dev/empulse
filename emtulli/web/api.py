import json
import logging
from fastapi import APIRouter, Request
from fastapi.responses import Response
from emtulli.app import templates
from emtulli.config import settings
from emtulli.database import get_db
from emtulli.db import history as history_db, stats as stats_db
from emtulli.models import SessionInfo, HistoryRecord

logger = logging.getLogger("emtulli.api")
router = APIRouter()


@router.get("/now-playing")
async def now_playing(request: Request):
    sessions = []
    state_tracker = getattr(request.app.state, "state_tracker", None)
    if state_tracker:
        sessions = [SessionInfo(**s) for s in state_tracker.get_all_sessions()]
    return templates.TemplateResponse("partials/now_playing.html", {
        "request": request, "sessions": sessions,
    })


@router.get("/stats-cards")
async def stats_cards(request: Request, days: int = 30, metric: str = "plays"):
    try:
        return await _stats_cards(request, days, metric)
    except Exception as e:
        logger.exception("stats-cards error")
        return f'<p class="empty-state">Error: {e}</p>'


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
    })


@router.get("/history-table")
async def history_table(
    request: Request,
    page: int = 1,
    search: str = "",
    user_id: str = "",
    item_type: str = "",
    play_method: str = "",
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
    )
    total = await history_db.get_history_count(
        db, user_id=user_id or None,
        item_type=item_type or None,
        play_method=play_method or None,
        search=search or None,
    )
    records = [HistoryRecord(**r) for r in rows]
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Build filter params for pagination links
    filter_params = ""
    if user_id:
        filter_params += f"&user_id={user_id}"
    if item_type:
        filter_params += f"&item_type={item_type}"
    if play_method:
        filter_params += f"&play_method={play_method}"
    if search:
        filter_params += f"&search={search}"

    return templates.TemplateResponse("partials/history_table.html", {
        "request": request, "records": records,
        "page": page, "total_pages": total_pages,
        "filter_params": filter_params,
    })


@router.get("/img/{item_id}")
async def image_proxy(item_id: str):
    """Proxy Emby item images so the API key stays server-side."""
    import httpx
    url = f"{settings.emby_url.rstrip('/')}/Items/{item_id}/Images/Primary"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"api_key": settings.emby_api_key, "maxWidth": "150"})
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


@router.get("/img/user/{user_id}")
async def user_image_proxy(user_id: str):
    """Proxy Emby user images."""
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


@router.post("/test-connection")
async def test_connection(request: Request):
    emby_client = getattr(request.app.state, "emby_client", None)
    if not emby_client:
        from emtulli.emby.client import EmbyClient
        emby_client = EmbyClient()

    try:
        info = await emby_client.get_server_info()
        db = get_db()
        from emtulli.db.libraries import upsert_server_info
        await upsert_server_info(db, {
            "server_name": info.get("ServerName", ""),
            "version": info.get("Version", ""),
            "local_address": info.get("LocalAddress", ""),
            "wan_address": info.get("WanAddress", ""),
            "os": info.get("OperatingSystem", ""),
        })
        return f'<p class="success">Connected to {info.get("ServerName", "Emby")} v{info.get("Version", "?")}</p>'
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return f'<p class="error">Connection failed: {e}</p>'
