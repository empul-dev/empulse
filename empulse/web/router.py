import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import hmac
import httpx

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from empulse.app import templates
from empulse.config import settings
from empulse.database import get_db
from empulse.db import users as users_db, libraries as libraries_db, history as history_db, stats as stats_db
from empulse.models import UserInfo, HistoryRecord
from empulse.web.auth import (
    create_session_token, hash_token, COOKIE_NAME, SESSION_MAX_AGE,
)

logger = logging.getLogger("empulse.router")

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"active": "dashboard"})


@router.get("/history")
async def history_page(request: Request):
    db = get_db()
    all_users = await users_db.get_all_users(db)
    user_list = [UserInfo(**u) for u in all_users]
    return templates.TemplateResponse(request, "history.html", {
        "active": "history", "users": user_list,
    })


@router.get("/users")
async def users_page(request: Request):
    db = get_db()
    all_users = await users_db.get_all_users(db)
    user_list = [UserInfo(**u) for u in all_users]
    return templates.TemplateResponse(request, "users.html", {
        "active": "users", "users": user_list,
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
    return templates.TemplateResponse(request, "user.html", {
        "active": "users",
        "user": user, "user_stats": user_stats,
        "most_watched": most_watched, "history": history_list,
    })


@router.get("/item/{item_id}")
async def item_detail(request: Request, item_id: str, type: str = "", name: str = ""):
    db = get_db()
    emby_client = getattr(request.app.state, "emby_client", None)
    requested_type = type

    async def _load_item(target_id: str) -> dict:
        if not emby_client:
            return {}
        try:
            return await emby_client.get_item(target_id)
        except Exception as e:
            logger.warning(f"Could not fetch item {target_id}: {e}")
            return {}

    # Fetch item metadata from Emby
    item_data = {}
    if emby_client:
        item_data = await _load_item(item_id)
        if requested_type == "series":
            resolved_series_id = item_data.get("SeriesId")
            if item_data.get("Type") != "Series" and resolved_series_id and resolved_series_id != item_id:
                series_item = await _load_item(resolved_series_id)
                if series_item:
                    item_data = series_item
                    item_id = resolved_series_id

    # Fallback to local history data when Emby returns nothing (404 / deleted items)
    local_record = None
    if not item_data:
        import json as _json
        if requested_type == "series" and name:
            cursor = await db.execute(
                "SELECT item_id, item_name, item_type, year, series_name, series_id, "
                "season_number, episode_number, runtime_ticks, stream_info "
                "FROM history WHERE series_name = ? ORDER BY started_at DESC LIMIT 1",
                [name],
            )
        else:
            cursor = await db.execute(
                "SELECT item_id, item_name, item_type, year, series_name, series_id, "
                "season_number, episode_number, runtime_ticks, stream_info "
                "FROM history WHERE item_id = ? ORDER BY started_at DESC LIMIT 1",
                [item_id],
            )
        local_record = await cursor.fetchone()
        if local_record:
            rec = dict(local_record)
            if requested_type == "series" and rec.get("series_id"):
                item_id = rec["series_id"]
            item_data = {
                "Id": item_id,
                "Name": (name or rec.get("series_name") or rec.get("item_name") or "Unknown"),
                "Type": "Series" if requested_type == "series" else (rec.get("item_type") or ""),
                "ProductionYear": rec.get("year"),
                "SeriesName": rec.get("series_name") or "",
                "SeriesId": rec.get("series_id") or "",
                "ParentIndexNumber": rec.get("season_number"),
                "IndexNumber": rec.get("episode_number"),
                "RunTimeTicks": rec.get("runtime_ticks") or 0,
            }
            # Parse stream_info JSON for video/audio badges
            try:
                si = _json.loads(rec.get("stream_info") or "{}")
                if si.get("video"):
                    v = si["video"]
                    item_data["_local_video"] = {
                        "Codec": v.get("codec", ""),
                        "Height": v.get("height"),
                        "Width": v.get("width"),
                    }
                if si.get("audio"):
                    a = si["audio"]
                    item_data["_local_audio"] = {
                        "Codec": a.get("codec", ""),
                        "Channels": a.get("channels"),
                    }
            except (_json.JSONDecodeError, TypeError):
                pass

    # For series/episodes, use series name for stats
    is_series = type == "series" or item_data.get("Type") in ("Series", "Episode")
    series_name = name or item_data.get("SeriesName") or item_data.get("Name", "")
    series_id = item_data.get("SeriesId", "")
    poster_id = series_id if is_series and series_id else item_id
    backdrop_id = series_id if is_series and series_id else item_id

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

    # Media info from MediaStreams or local fallback
    media_streams = item_data.get("MediaStreams", [])
    video_stream = next((s for s in media_streams if s.get("Type") == "Video"), {})
    audio_stream = next((s for s in media_streams if s.get("Type") == "Audio"), {})

    # Use local stream info if Emby didn't provide MediaStreams
    if not video_stream and item_data.get("_local_video"):
        video_stream = item_data["_local_video"]
    if not audio_stream and item_data.get("_local_audio"):
        audio_stream = item_data["_local_audio"]

    runtime_ticks = item_data.get("RunTimeTicks", 0)
    runtime_mins = int(runtime_ticks / 600_000_000) if runtime_ticks else 0

    # Premiere date
    premiere = item_data.get("PremiereDate", "")
    aired = premiere[:10] if len(premiere) >= 10 else ""

    # Production year fallback (show year if available and no aired date)
    year = item_data.get("ProductionYear")

    # Ratings and external links
    community_rating = item_data.get("CommunityRating")
    critic_rating = item_data.get("CriticRating")
    official_rating = item_data.get("OfficialRating", "")
    tagline = (item_data.get("Taglines") or [""])[0]
    original_title = item_data.get("OriginalTitle", "")
    external_urls = item_data.get("ExternalUrls", [])

    # ProviderIds (IMDB/TMDB) — keys are inconsistently capitalized in Emby
    provider_ids = item_data.get("ProviderIds", {})
    imdb_id = provider_ids.get("Imdb") or provider_ids.get("IMDB") or provider_ids.get("imdb", "")
    tmdb_id = provider_ids.get("Tmdb") or provider_ids.get("TMDB") or provider_ids.get("tmdb", "")

    return templates.TemplateResponse(request, "item.html", {
        "active": "",
        "item": item_data,
        "item_id": item_id,
        "poster_id": poster_id,
        "backdrop_id": backdrop_id,
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
        "year": year,
        "community_rating": community_rating,
        "critic_rating": critic_rating,
        "official_rating": official_rating,
        "tagline": tagline,
        "original_title": original_title,
        "external_urls": external_urls,
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
        "global_stats": global_stats,
        "user_stats": user_stats,
    })


@router.get("/graphs")
async def graphs_page(request: Request):
    return templates.TemplateResponse(request, "graphs.html", {
        "active": "graphs",
    })


@router.get("/libraries")
async def libraries_page(request: Request):
    db = get_db()
    all_libs = await libraries_db.get_all_libraries(db)
    return templates.TemplateResponse(request, "libraries.html", {
        "active": "libraries",
        "libraries": all_libs,
    })


@router.get("/unwatched")
@router.get("/series/unwatched")
async def unwatched_page(
    request: Request,
    page: int = 1,
    page_size: int = 48,
    search: str = "",
    sort: str = "name_asc",
    library_id: str = "",
):
    db = get_db()
    all_libraries = await libraries_db.get_all_libraries(db)
    initial_query = urlencode(
        {
            "page": max(1, page),
            "page_size": max(1, min(page_size, 100)),
            "search": search,
            "sort": sort,
            "library_id": library_id,
        }
    )

    return templates.TemplateResponse(request, "unwatched.html", {
        "active": "unwatched",
        "page": max(1, page),
        "page_size": max(1, min(page_size, 100)),
        "search": search,
        "sort": sort,
        "library_id": library_id,
        "libraries": all_libraries,
        "initial_query": initial_query,
    })


@router.get("/libraries/{item_type}")
async def library_detail(request: Request, item_type: str):
    db = get_db()
    type_labels = {"Movie": "Movies", "Episode": "TV Shows", "Audio": "Music"}
    label = type_labels.get(item_type, item_type)
    lib_stats = await stats_db.get_library_stats(db, item_type)
    top_items = await stats_db.get_library_top_items(db, item_type, limit=10, days=30)
    top_users = await stats_db.get_library_top_users(db, item_type, limit=10, days=30)
    return templates.TemplateResponse(request, "library.html", {
        "active": "libraries",
        "item_type": item_type, "label": label,
        "lib_stats": lib_stats, "top_items": top_items, "top_users": top_users,
    })


_LOGIN_ERRORS = {
    "invalid": "Invalid username or password.",
    "rate_limited": "Too many attempts. Please try again later.",
    "rejected": "Request rejected.",
    "emby_down": "Emby server is unavailable. Try the local admin password.",
    "disabled": "Your account has not been enabled yet. Ask an admin to enable it.",
}


@router.get("/login")
async def login_page(request: Request, error: str = ""):
    error_msg = _LOGIN_ERRORS.get(error, "")
    has_fallback = bool(settings.auth_password)
    auth_configured = bool(settings.auth_password or settings.emby_api_key)
    return templates.TemplateResponse(request, "login.html", {
        "active": "", "error": error_msg,
        "has_fallback": has_fallback,
        "auth_configured": auth_configured,
    })


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
):
    from empulse.web.auth import login_limiter, check_origin

    client_ip = request.client.host if request.client else "unknown"

    if not check_origin(request):
        return RedirectResponse("/login?error=rejected", status_code=302)

    if login_limiter.is_limited(client_ip, username):
        return RedirectResponse("/login?error=rate_limited", status_code=302)

    if not password:
        return RedirectResponse("/login?error=invalid", status_code=302)

    user_id = None
    display_name = None
    role = None

    # Try Emby authentication first
    emby_client = getattr(request.app.state, "emby_client", None)
    emby_down = False
    if emby_client and username:
        try:
            result = await emby_client.authenticate_user(username, password)
            if result:
                user_id = result["user_id"]
                display_name = result["username"]
                role = "admin" if result["is_admin"] else "viewer"
            else:
                # Bad credentials via Emby
                login_limiter.record(client_ip, username)
                return RedirectResponse("/login?error=invalid", status_code=302)
        except (httpx.TimeoutException, httpx.ConnectError):
            logger.warning("Emby unavailable for auth, trying fallback")
            emby_down = True
        except httpx.HTTPStatusError as e:
            logger.error(f"Emby auth error: {e}")
            emby_down = True

    # Fallback: AUTH_PASSWORD (works when Emby is down or no username given)
    if user_id is None and settings.auth_password:
        if hmac.compare_digest(password, settings.auth_password):
            user_id = "__admin__"
            display_name = username or "Admin"
            role = "admin"
        elif not emby_down:
            # Password didn't match fallback, and Emby wasn't tried / didn't error
            login_limiter.record(client_ip, username)
            return RedirectResponse("/login?error=invalid", status_code=302)

    # If Emby was down and fallback password didn't match
    if user_id is None and emby_down:
        if settings.auth_password:
            login_limiter.record(client_ip, username)
            return RedirectResponse("/login?error=invalid", status_code=302)
        return RedirectResponse("/login?error=emby_down", status_code=302)

    if user_id is None:
        login_limiter.record(client_ip, username)
        return RedirectResponse("/login?error=invalid", status_code=302)

    # Create session token and DB entry
    token = create_session_token(settings.secret_key, user_id, role)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=SESSION_MAX_AGE)

    db = get_db()
    await db.execute(
        """INSERT INTO login_sessions
           (token_hash, emby_user_id, username, role, created_at, expires_at, ip_address, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            hash_token(token),
            user_id if user_id != "__admin__" else None,
            display_name,
            role,
            now.isoformat(),
            expires.isoformat(),
            client_ip,
            request.headers.get("user-agent", "")[:256],
        ],
    )

    # Upsert user in users table (sync is_admin from Emby)
    if user_id != "__admin__":
        await users_db.upsert_user(db, {
            "emby_user_id": user_id,
            "username": display_name,
            "is_admin": 1 if role == "admin" else 0,
            "thumb_url": None,
            "last_seen": now.isoformat(),
        })
        # Emby admins are auto-enabled
        if role == "admin":
            await users_db.set_user_enabled(db, user_id, True)
        # Check if user account is enabled
        if not await users_db.is_user_enabled(db, user_id):
            # Remove the session we just inserted
            await db.execute(
                "DELETE FROM login_sessions WHERE token_hash = ?",
                [hash_token(token)],
            )
            await db.commit()
            return RedirectResponse("/login?error=disabled", status_code=302)

    await db.commit()

    login_limiter.reset(client_ip)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True, samesite="lax", max_age=SESSION_MAX_AGE,
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db = get_db()
        await db.execute(
            "UPDATE login_sessions SET revoked = 1 WHERE token_hash = ?",
            [hash_token(token)],
        )
        await db.commit()
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/settings")
async def settings_page(request: Request):
    db = get_db()
    server_info = await libraries_db.get_server_info(db)
    update_checker = getattr(request.app.state, "update_checker", None)
    update_info = update_checker.info if update_checker else None
    return templates.TemplateResponse(request, "settings.html", {
        "active": "settings",
        "settings": settings, "server_info": server_info,
        "update_info": update_info,
        "update_check_enabled": bool(update_checker),
    })


@router.get("/settings/newsletter")
async def settings_newsletter(request: Request):
    db = get_db()
    from empulse.newsletter import get_newsletter_config
    config = await get_newsletter_config(db)
    if config and config.get("smtp_pass"):
        config = {**config, "smtp_pass": "***"}
    return templates.TemplateResponse(request, "settings_newsletter.html", {
        "active": "settings",
        "config": config or {},
    })


@router.get("/settings/notifications")
async def settings_notifications(request: Request):
    db = get_db()
    cursor = await db.execute("SELECT * FROM notification_channels ORDER BY created_at DESC")
    channels = [dict(r) for r in await cursor.fetchall()]
    cursor = await db.execute("SELECT * FROM notification_log ORDER BY sent_at DESC LIMIT 20")
    logs = [dict(r) for r in await cursor.fetchall()]
    return templates.TemplateResponse(request, "settings_notifications.html", {
        "active": "settings",
        "channels": channels, "logs": logs,
    })
