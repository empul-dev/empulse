from fastapi import Request
from starlette.responses import Response

from empulse.database import get_db


def get_database():
    return get_db()


def forbidden_response(request: Request) -> Response:
    """Shared 403 response: bare status for htmx requests, rendered page otherwise.

    Mirrors AuthMiddleware._forbidden so both the middleware's admin-route gate
    and per-endpoint self-or-admin checks behave identically.
    """
    if request.headers.get("hx-request"):
        return Response(status_code=403)
    from empulse.app import templates

    return templates.TemplateResponse(request, "403.html", status_code=403)


def require_self_or_admin(request: Request, user_id: str) -> Response | None:
    """Return a 403 response unless the current session user is an admin or
    is viewing their own data, else None."""
    user = getattr(request.state, "user", None)
    if not user:
        return forbidden_response(request)
    if user.role == "admin" or user.user_id == user_id:
        return None
    return forbidden_response(request)


def scoped_user_filter(request: Request, user_id: str) -> str | None:
    """Resolve the effective user_id filter for list/export endpoints.

    Admins can filter by any user_id (or none, for "all users"). Non-admins
    are always scoped to their own user_id, regardless of what was requested —
    silently, so no information is leaked about other accounts.
    """
    user = getattr(request.state, "user", None)
    if user and user.role == "admin":
        return user_id or None
    if user:
        return user.user_id
    return user_id or None
