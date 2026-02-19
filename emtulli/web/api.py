import json
import logging
from fastapi import APIRouter, Request
from emtulli.app import templates
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
async def stats_cards(request: Request):
    db = get_db()
    total_plays = await stats_db.get_total_plays(db)
    total_duration = await stats_db.get_total_duration(db)
    plays_per_day = await stats_db.get_plays_per_day(db, days=30)

    state_tracker = getattr(request.app.state, "state_tracker", None)
    active_streams = len(state_tracker.get_all_sessions()) if state_tracker else 0

    # Format duration
    m, _ = divmod(total_duration, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        dur = f"{d}d {h}h"
    else:
        dur = f"{h}h {m}m"

    return templates.TemplateResponse("partials/stats_cards.html", {
        "request": request,
        "total_plays": total_plays,
        "total_duration_display": dur,
        "active_streams": active_streams,
        "plays_per_day": plays_per_day,
        "plays_per_day_json": json.dumps(plays_per_day),
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
):
    db = get_db()
    per_page = 50
    offset = (page - 1) * per_page

    rows = await history_db.get_history(
        db, limit=per_page, offset=offset,
        user_id=user_id or None,
        item_type=item_type or None,
        search=search or None,
    )
    total = await history_db.get_history_count(
        db, user_id=user_id or None,
        item_type=item_type or None,
        search=search or None,
    )
    records = [HistoryRecord(**r) for r in rows]
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("partials/history_table.html", {
        "request": request, "records": records,
        "page": page, "total_pages": total_pages,
    })


@router.post("/test-connection")
async def test_connection(request: Request):
    emby_client = getattr(request.app.state, "emby_client", None)
    if not emby_client:
        from emtulli.emby.client import EmbyClient
        emby_client = EmbyClient()

    try:
        info = await emby_client.get_server_info()
        # Save server info
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
