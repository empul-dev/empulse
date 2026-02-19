import logging

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from emtulli.app import templates
from emtulli.config import settings
from emtulli.database import get_db
from emtulli.db import users as users_db, libraries as libraries_db, history as history_db, stats as stats_db
from emtulli.models import UserInfo, HistoryRecord
from emtulli.web.auth import create_session_token, COOKIE_NAME

logger = logging.getLogger("emtulli.router")

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "active": "dashboard"})


@router.get("/history")
async def history_page(request: Request):
    db = get_db()
    all_users = await users_db.get_all_users(db)
    user_list = [UserInfo(**u) for u in all_users]
    return templates.TemplateResponse("history.html", {
        "request": request, "active": "history", "users": user_list,
    })


@router.get("/users")
async def users_page(request: Request):
    db = get_db()
    all_users = await users_db.get_all_users(db)
    user_list = [UserInfo(**u) for u in all_users]
    return templates.TemplateResponse("users.html", {
        "request": request, "active": "users", "users": user_list,
    })


@router.get("/users/{user_id}")
async def user_detail(request: Request, user_id: str):
    db = get_db()
    user_data = await users_db.get_user(db, user_id)
    if not user_data:
        user_data = {"emby_user_id": user_id, "username": "Unknown", "total_plays": 0, "total_duration": 0}
    user = UserInfo(**user_data)
    user_stats = await stats_db.get_user_stats(db, user_id)
    most_watched = await stats_db.get_user_most_watched(db, user_id, limit=10, days=30)
    history_rows = await history_db.get_history_for_user(db, user_id, limit=50)
    history_list = [HistoryRecord(**r) for r in history_rows]
    return templates.TemplateResponse("user.html", {
        "request": request, "active": "users",
        "user": user, "user_stats": user_stats,
        "most_watched": most_watched, "history": history_list,
    })


@router.get("/item/{item_id}")
async def item_detail(request: Request, item_id: str, type: str = "", name: str = ""):
    db = get_db()
    emby_client = getattr(request.app.state, "emby_client", None)

    # Fetch item metadata from Emby
    item_data = {}
    if emby_client:
        try:
            item_data = await emby_client.get_item(item_id)
        except Exception as e:
            logger.warning(f"Could not fetch item {item_id}: {e}")

    # For series, use series name for stats
    is_series = type == "series" or item_data.get("Type") == "Series"
    series_name = name or item_data.get("SeriesName") or item_data.get("Name", "")

    if is_series and series_name:
        global_stats = await stats_db.get_series_stats(db, series_name)
        user_stats = await stats_db.get_series_user_stats(db, series_name)
    else:
        global_stats = await stats_db.get_item_stats(db, item_id)
        user_stats = await stats_db.get_item_user_stats(db, item_id)

    # Extract metadata
    people = item_data.get("People", [])
    directors = [p["Name"] for p in people if p.get("Type") == "Director"]
    actors = [p["Name"] for p in people if p.get("Type") == "Actor"][:6]
    writers = [p["Name"] for p in people if p.get("Type") == "Writer"][:3]
    genres = item_data.get("Genres", [])
    studios = [s["Name"] for s in item_data.get("Studios", [])] if item_data.get("Studios") else []

    # Media info from MediaStreams
    media_streams = item_data.get("MediaStreams", [])
    video_stream = next((s for s in media_streams if s.get("Type") == "Video"), {})
    audio_stream = next((s for s in media_streams if s.get("Type") == "Audio"), {})

    runtime_ticks = item_data.get("RunTimeTicks", 0)
    runtime_mins = int(runtime_ticks / 600_000_000) if runtime_ticks else 0

    # Premiere date
    premiere = item_data.get("PremiereDate", "")
    aired = premiere[:10] if len(premiere) >= 10 else ""

    return templates.TemplateResponse("item.html", {
        "request": request,
        "active": "",
        "item": item_data,
        "item_id": item_id,
        "is_series": is_series,
        "series_name": series_name,
        "directors": directors,
        "actors": actors,
        "writers": writers,
        "genres": genres,
        "studios": studios,
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "runtime_mins": runtime_mins,
        "aired": aired,
        "global_stats": global_stats,
        "user_stats": user_stats,
    })


@router.get("/libraries")
async def libraries_page(request: Request):
    db = get_db()
    all_libs = await libraries_db.get_all_libraries(db)
    return templates.TemplateResponse("libraries.html", {
        "request": request, "active": "libraries",
        "libraries": all_libs,
    })


@router.get("/libraries/{item_type}")
async def library_detail(request: Request, item_type: str):
    db = get_db()
    type_labels = {"Movie": "Movies", "Episode": "TV Shows", "Audio": "Music"}
    label = type_labels.get(item_type, item_type)
    lib_stats = await stats_db.get_library_stats(db, item_type)
    top_items = await stats_db.get_library_top_items(db, item_type, limit=10, days=30)
    top_users = await stats_db.get_library_top_users(db, item_type, limit=10, days=30)
    return templates.TemplateResponse("library.html", {
        "request": request, "active": "libraries",
        "item_type": item_type, "label": label,
        "lib_stats": lib_stats, "top_items": top_items, "top_users": top_users,
    })


@router.get("/login")
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {
        "request": request, "active": "", "error": error,
    })


@router.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    if settings.auth_password and password == settings.auth_password:
        secret = settings.secret_key or settings.auth_password
        token = create_session_token(secret)
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            COOKIE_NAME, token,
            httponly=True, samesite="lax", max_age=30 * 24 * 3600,
        )
        return response
    return templates.TemplateResponse("login.html", {
        "request": request, "active": "", "error": "Invalid password",
    })


@router.get("/settings")
async def settings_page(request: Request):
    db = get_db()
    server_info = await libraries_db.get_server_info(db)
    return templates.TemplateResponse("settings.html", {
        "request": request, "active": "settings",
        "settings": settings, "server_info": server_info,
    })
