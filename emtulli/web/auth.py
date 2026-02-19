import hashlib
import hmac
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

COOKIE_NAME = "emtulli_session"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 days


def create_session_token(secret: str) -> str:
    """Create an HMAC-signed timestamp token."""
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def verify_session_token(token: str, secret: str) -> bool:
    """Verify an HMAC-signed timestamp token."""
    try:
        ts, sig = token.split(".", 1)
        expected = hmac.new(secret.encode(), ts.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        age = time.time() - int(ts)
        return 0 <= age <= SESSION_MAX_AGE
    except (ValueError, TypeError):
        return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Password-based auth middleware. Only active if password is configured."""

    EXCLUDED_PREFIXES = ("/login", "/static", "/ws")

    def __init__(self, app, password: str = "", secret: str = ""):
        super().__init__(app)
        self.password = password
        self.secret = secret or password

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.password:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in self.EXCLUDED_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if token and verify_session_token(token, self.secret):
            return await call_next(request)

        # Check if HTMX request
        if request.headers.get("hx-request"):
            return Response(status_code=401)

        return RedirectResponse("/login", status_code=302)
