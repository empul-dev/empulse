from fastapi import APIRouter, Request
from emtulli.app import templates
from emtulli.config import settings
from emtulli.database import get_db
from emtulli.db import users as users_db, libraries as libraries_db, history as history_db, stats as stats_db
from emtulli.models import UserInfo, HistoryRecord

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
    history_rows = await history_db.get_history_for_user(db, user_id, limit=50)
    history_list = [HistoryRecord(**r) for r in history_rows]
    return templates.TemplateResponse("user.html", {
        "request": request, "active": "users",
        "user": user, "user_stats": user_stats, "history": history_list,
    })


@router.get("/libraries")
async def libraries_page(request: Request):
    db = get_db()
    all_libs = await libraries_db.get_all_libraries(db)
    return templates.TemplateResponse("libraries.html", {
        "request": request, "active": "libraries",
        "libraries": all_libs,
    })


@router.get("/settings")
async def settings_page(request: Request):
    db = get_db()
    server_info = await libraries_db.get_server_info(db)
    return templates.TemplateResponse("settings.html", {
        "request": request, "active": "settings",
        "settings": settings, "server_info": server_info,
    })
